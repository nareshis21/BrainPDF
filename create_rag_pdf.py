"""
RAG Resume PDF Generator
Reads a resume PDF, semantically chunks it, builds TF-IDF index,
and generates a new PDF with embedded search + Groq API chat via proxy.
"""

import sys
import json
import math
import re
from collections import Counter

import fitz  # PyMuPDF
from pypdf import PdfReader


# ═══════════════════════════════════════════════════════════════════════════
# STOP WORDS
# ═══════════════════════════════════════════════════════════════════════════

STOP_WORDS = set(
    "a an the is are was were be been being have has had do does did "
    "will would shall should may might can could and or but if then else "
    "when where how what which who whom this that these those it its i me "
    "my we our you your he him his she her they them their in on at to "
    "for with by from of as not no so very also just than more most other "
    "some such only over after before between through during about into "
    "up out down off again further once here there all each every both "
    "few many much any same own too".split()
)

def tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())


# ═══════════════════════════════════════════════════════════════════════════
# SEMANTIC CHUNKING
# ═══════════════════════════════════════════════════════════════════════════

def extract_and_chunk_resume(pdf_path):
    reader = PdfReader(pdf_path)
    full_text = ""
    for page in reader.pages:
        full_text += (page.extract_text() or "") + "\n"

    sections = re.split(
        r'\n(?=EDUCATION\n|EXPERIENCE\n|PROJECTS\n|PUBLICATIONS\n|TECHNICAL EXPERTISE\n|CERTIFICATIONS\n)',
        full_text
    )

    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        lines = section.split('\n')
        header = lines[0].strip()

        if header in ("EXPERIENCE", "PROJECTS"):
            sub_sections = re.split(r'\n(?=[A-Z][a-zA-Z\s]+–|•|Repo\s–)', section[len(header):])
            current = header + ": "
            for sub in sub_sections:
                sub = sub.strip()
                if not sub: continue
                if len(current.split()) + len(sub.split()) > 120:
                    chunks.append({"section": header, "text": current.strip()})
                    current = header + ": " + sub + "\n"
                else:
                    current += sub + "\n"
            if len(current.split()) > 3:
                chunks.append({"section": header, "text": current.strip()})
        else:
            clean_text = section.replace('\n', ' ').strip()
            if header not in ["EDUCATION", "PROJECTS", "PUBLICATIONS", "TECHNICAL EXPERTISE", "CERTIFICATIONS"]:
                header = "CONTACT_AND_SUMMARY"
            chunks.append({"section": header, "text": clean_text})

    return [c for c in chunks if len(c["text"].split()) > 5]


# ═══════════════════════════════════════════════════════════════════════════
# TF-IDF ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def build_tfidf(chunks):
    tokenized = []
    for chunk in chunks:
        tokens = [t for t in tokenize(chunk["text"]) if t not in STOP_WORDS and len(t) > 1]
        tokenized.append(tokens)

    df = Counter()
    for tokens in tokenized:
        df.update(set(tokens))

    vocab_list = list(df.keys())
    vocab = {w: i for i, w in enumerate(vocab_list)}

    n = len(chunks)
    idf = [0.0] * len(vocab_list)
    for word, idx in vocab.items():
        idf[idx] = round(math.log(n / (1 + df[word])) + 1, 4)

    vectors = []
    for tokens in tokenized:
        tf = Counter(tokens)
        vec = []
        norm_sq = 0
        for word, count in tf.items():
            if word in vocab:
                idx = vocab[word]
                w = count * idf[idx]
                vec.append([idx, w])
                norm_sq += w * w
        norm = math.sqrt(norm_sq) or 1
        vec = [[idx, round(w / norm, 4)] for idx, w in vec]
        vectors.append(vec)

    return vocab, idf, vectors


# ═══════════════════════════════════════════════════════════════════════════
# RAG JAVASCRIPT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

BTN_JS_TEMPLATE = r"""
try {
    var _vocab = %VOCAB%;
    var _idf  = %IDF%;
    var _vecs = %VECS%;
    var _chnk = %CHUNKS%;
    var _sw   = %SW%;

    function _tok(text) {
      var r = [], w = "", lo = text.toLowerCase();
      for (var i = 0; i <= lo.length; i++) {
        var c = i < lo.length ? lo.charCodeAt(i) : 32;
        if ((c >= 97 && c <= 122) || (c >= 48 && c <= 57)) { w += lo.charAt(i); }
        else { if (w.length > 1 && !_sw[w]) r.push(w); w = ""; }
      }
      return r;
    }

    function _qvec(text) {
      var tokens = _tok(text), tf = {};
      for (var i = 0; i < tokens.length; i++) {
        var idx = _vocab[tokens[i]];
        if (idx !== undefined) tf[idx] = (tf[idx] || 0) + 1;
      }
      var vec = {}, norm = 0;
      for (var k in tf) { var wt = tf[k] * _idf[k]; vec[k] = wt; norm += wt * wt; }
      norm = Math.sqrt(norm) || 1;
      for (var k in vec) vec[k] /= norm;
      return vec;
    }

    function _cos(qv, dv) {
      var dot = 0;
      for (var i = 0; i < dv.length; i++) {
        if (qv[dv[i][0]]) dot += qv[dv[i][0]] * dv[i][1];
      }
      return dot;
    }

    // --- Main Logic ---
    var promptField = this.getField("UserPrompt");
    var q = promptField.valueAsString || promptField.value;

    if (!q || q.trim().length < 1) {
      this.getField("StatusField").value = "Please enter a question first.";
    } else {
      var tokens = _tok(q);
      var matchedTerms = [];
      for (var i=0; i<tokens.length; i++) {
        if (_vocab[tokens[i]] !== undefined) matchedTerms.push(tokens[i]);
      }

      var debugLabel = "Query Tokens: [" + tokens.join(", ") + "]";
      if (tokens.length > 0) {
        debugLabel += " | Matches Found: [" + matchedTerms.join(", ") + "]";
      }

      this.getField("StatusField").value = "Searching... " + debugLabel;
      this.getField("RetrievedChunks").value = "";
      this.getField("ApiResponse").value = "";

      var qv = _qvec(q);
      var sc = [];
      for (var i = 0; i < _vecs.length; i++) {
        var s = _cos(qv, _vecs[i]);
        sc.push([i, s]);
      }
      sc.sort(function(a, b) { return b[1] - a[1]; });

      var topChunks = [], chunkDisplay = "";
      var sep = "========================================\n";
      for (var i = 0; i < 4 && i < sc.length; i++) {
         var ci = sc[i][0];
         var score = Math.round(sc[i][1] * 1000) / 1000;
         topChunks.push("Section: " + _chnk[ci].s + "\nText: " + _chnk[ci].t);
         chunkDisplay += sep;
         chunkDisplay += "Chunk " + (i+1) + " [" + _chnk[ci].s + "] (Score: " + score + ")\n";
         chunkDisplay += sep;
         chunkDisplay += _chnk[ci].t + "\n\n\n";
      }

      this.getField("RetrievedChunks").value = chunkDisplay;

      var docData = {
          prompt: q,
          context: topChunks.join("\n\n"),
          timestamp: new Date().getTime()
      };

      this.getField("HiddenJSONData").value = JSON.stringify(docData);
      
      if (matchedTerms.length == 0 && tokens.length > 0) {
          this.getField("StatusField").value = "Note: No word matches for: " + tokens.join(", ");
      } else {
          this.getField("StatusField").value = "Asking Groq AI...";
      }

      this.submitForm({
          cURL: "%PROXY_URL%",
          bEmpty: false,
          cSubmitAs: "HTML"
      });
    }
} catch(e) {
    app.alert("Script Error: " + e);
}
"""

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
# IMPORTANT: After deploying to Vercel, replace this link with your live URL!
# e.g. PROXY_URL = "https://your-app.vercel.app/generate-rag-fdf"
PROXY_URL = "http://localhost:3000/generate-rag-fdf" 


# ═══════════════════════════════════════════════════════════════════════════
# PDF GENERATOR
# ═══════════════════════════════════════════════════════════════════════════

def generate_rag_pdf(input_pdf, output_pdf):
    print(f"[1/4] Reading & Extracting: {input_pdf}")
    chunks = extract_and_chunk_resume(input_pdf)
    if not chunks:
        print("Error: No extractable text found.")
        sys.exit(1)

    print(f"       Created {len(chunks)} semantic chunks:")
    for i, c in enumerate(chunks):
        print(f"         {i+1}. [{c['section']}] {len(c['text'].split())} words")

    print("[2/4] Building TF-IDF index...")
    vocab, idf, vectors = build_tfidf(chunks)

    # ── Prepare JS data ──
    vocab_json = json.dumps(vocab, ensure_ascii=True)
    idf_json = json.dumps(idf, ensure_ascii=True)
    vecs_json = json.dumps(vectors, ensure_ascii=True)
    chunks_json = json.dumps([{"s": c["section"], "t": c["text"]} for c in chunks], ensure_ascii=True)
    sw_json = json.dumps({w: 1 for w in STOP_WORDS}, ensure_ascii=True)

    # ── Build the JS ──
    btn_js = BTN_JS_TEMPLATE.replace("%VOCAB%", vocab_json)\
                            .replace("%IDF%", idf_json)\
                            .replace("%VECS%", vecs_json)\
                            .replace("%CHUNKS%", chunks_json)\
                            .replace("%SW%", sw_json)\
                            .replace("%PROXY_URL%", PROXY_URL)

    # ── Layout ──
    pw, ph = 612, 920
    m = 40
    cw = pw - 2 * m

    print("[3/4] Building PDF with fitz...")
    doc = fitz.open()

    # ══════════════════════════════════════════
    # PAGE 1-N: Insert original resume pages
    # ══════════════════════════════════════════
    resume_doc = fitz.open(input_pdf)
    for i in range(len(resume_doc)):
        doc.insert_pdf(resume_doc, from_page=i, to_page=i)
    resume_doc.close()
    print(f"       Inserted {doc.page_count} resume page(s)")

    # ══════════════════════════════════════════
    # CHAT PAGE: Beautiful RAG Interface
    # ══════════════════════════════════════════
    page = doc.new_page(width=pw, height=ph)
    y = 0

    # ── Dark Header Bar ──
    header_h = 70
    page.draw_rect(fitz.Rect(0, 0, pw, header_h), fill=(0.12, 0.12, 0.22))
    page.insert_text((m, 28), "Resume AI Chat", fontsize=22, color=(1, 1, 1))
    page.insert_text((m, 48), "Retrieval-Augmented Generation  |  TF-IDF Search  |  Groq LLM", fontsize=8, color=(0.6, 0.7, 0.9))
    page.insert_text((m, 62), f"{len(chunks)} semantic chunks indexed  |  Full vocabulary search", fontsize=7, color=(0.5, 0.6, 0.7))
    y = header_h + 15

    # ── Prompt Section ──
    section_bg = fitz.Rect(m - 5, y - 5, pw - m + 5, y + 70)
    page.draw_rect(section_bg, fill=(0.96, 0.96, 1.0), color=(0.8, 0.8, 0.95), width=0.5)

    page.insert_text((m, y + 12), "Your Question", fontsize=10, color=(0.3, 0.3, 0.6))
    y += 18

    prompt_h = 40
    btn_w = 90

    prompt_widget = fitz.Widget()
    prompt_widget.rect = fitz.Rect(m, y, pw - m - btn_w - 10, y + prompt_h)
    prompt_widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    prompt_widget.field_name = "UserPrompt"
    prompt_widget.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
    prompt_widget.fill_color = (1, 1, 1)
    prompt_widget.border_color = (0.4, 0.4, 0.7)
    prompt_widget.text_fontsize = 11
    page.add_widget(prompt_widget)

    # ── Send Button ──
    btn_rect = fitz.Rect(pw - m - btn_w, y, pw - m, y + prompt_h)
    page.draw_rect(btn_rect, color=None, fill=(0.18, 0.5, 0.85))
    page.draw_rect(fitz.Rect(btn_rect.x0, btn_rect.y0, btn_rect.x1, btn_rect.y0 + 3), fill=(0.3, 0.65, 1.0))
    page.insert_text((btn_rect.x0 + 14, btn_rect.y0 + 18), "Send", fontsize=16, color=(1, 1, 1))
    page.insert_text((btn_rect.x0 + 14, btn_rect.y0 + 30), "to Groq AI", fontsize=7, color=(0.8, 0.9, 1.0))

    btn_widget = fitz.Widget()
    btn_widget.rect = btn_rect
    btn_widget.field_type = fitz.PDF_WIDGET_TYPE_BUTTON
    btn_widget.field_name = "SubmitBtn"
    btn_widget.field_flags = fitz.PDF_BTN_FIELD_IS_PUSHBUTTON
    btn_widget.script = btn_js
    page.add_widget(btn_widget)

    y += prompt_h + 12

    # ── Hidden JSON Data ──
    hidden_widget = fitz.Widget()
    hidden_widget.rect = fitz.Rect(0, ph - 1, 1, ph)
    hidden_widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    hidden_widget.field_name = "HiddenJSONData"
    page.add_widget(hidden_widget)

    # ── Status Bar ──
    status_h = 24
    status_bg = fitz.Rect(m - 5, y - 2, pw - m + 5, y + status_h + 2)
    page.draw_rect(status_bg, fill=(0.94, 0.94, 0.94), color=(0.85, 0.85, 0.85), width=0.3)
    page.insert_text((m + 2, y + 13), "Status:", fontsize=8, color=(0.4, 0.4, 0.4))

    status_widget = fitz.Widget()
    status_widget.rect = fitz.Rect(m + 40, y, pw - m, y + status_h)
    status_widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    status_widget.field_name = "StatusField"
    status_widget.field_value = "Ready. Type a question and click Send."
    status_widget.field_flags = 1
    status_widget.fill_color = (0.94, 0.94, 0.94)
    status_widget.border_color = (0.85, 0.85, 0.85)
    status_widget.text_fontsize = 8
    page.add_widget(status_widget)

    y += status_h + 12

    # ── Divider ──
    page.draw_line(fitz.Point(m, y), fitz.Point(pw - m, y), color=(0.7, 0.7, 0.85), width=1)
    y += 8

    # ── Retrieved Chunks Section ──
    page.draw_rect(fitz.Rect(m, y, m + 4, y + 14), fill=(0.9, 0.6, 0.1))
    page.insert_text((m + 10, y + 11), "Retrieved Context Chunks", fontsize=11, color=(0.15, 0.15, 0.3))
    y += 18

    chunks_h = 185
    chunks_widget = fitz.Widget()
    chunks_widget.rect = fitz.Rect(m, y, pw - m, y + chunks_h)
    chunks_widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    chunks_widget.field_name = "RetrievedChunks"
    chunks_widget.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE | 1
    chunks_widget.fill_color = (0.99, 0.97, 0.92)
    chunks_widget.border_color = (0.85, 0.75, 0.5)
    chunks_widget.text_fontsize = 7
    page.add_widget(chunks_widget)

    y += chunks_h + 12

    # ── Divider ──
    page.draw_line(fitz.Point(m, y), fitz.Point(pw - m, y), color=(0.5, 0.8, 0.5), width=1)
    y += 8

    # ── AI Response Section ──
    page.draw_rect(fitz.Rect(m, y, m + 4, y + 14), fill=(0.2, 0.6, 0.3))
    page.insert_text((m + 10, y + 11), "AI Response", fontsize=11, color=(0.1, 0.3, 0.1))
    y += 18

    response_h = ph - y - m - 20
    response_widget = fitz.Widget()
    response_widget.rect = fitz.Rect(m, y, pw - m, y + response_h)
    response_widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    response_widget.field_name = "ApiResponse"
    response_widget.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE | 1
    response_widget.fill_color = (0.95, 0.99, 0.95)
    response_widget.border_color = (0.5, 0.75, 0.5)
    response_widget.text_fontsize = 11
    page.add_widget(response_widget)

    # ── Footer ──
    page.draw_rect(fitz.Rect(0, ph - 20, pw, ph), fill=(0.12, 0.12, 0.22))
    page.insert_text((m, ph - 7), f"Built with PyMuPDF + Groq API | Page {doc.page_count}", fontsize=6, color=(0.5, 0.6, 0.7))

    # ── Save ──
    print("[4/4] Saving PDF...")
    final_page_count = doc.page_count
    doc.save(output_pdf)
    print(f"\nDone! RAG PDF: {output_pdf}")
    print(f"Resume pages: 1-{final_page_count - 1}, Chat UI: page {final_page_count}")
    doc.close()


if __name__ == "__main__":
    generate_rag_pdf("Naresh_Lahajal_resume.pdf", "Interactive_Resume_Chat.pdf")
