from flask import Flask, request, Response
import json
import re
import os
from datetime import datetime
from flask_cors import CORS
from dotenv import load_dotenv

# Load variables from .env if present
load_dotenv()

app = Flask(__name__)
CORS(app) # Allow cross-origin requests from PDF browsers

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

@app.route('/generate-fdf', methods=['POST'])
def generate_fdf():
    """
    Acts as a proxy between the PDF and external APIs.
    Receives form data from the PDF, processes it, and returns an FDF file
    to update the PDF's fields.
    """
    # 1. Extract data sent from the PDF
    # The PDF JavaScript sends it as a standard HTML form POST
    hidden_data = request.form.get('HiddenJSONData', "{}")
    try:
        pdf_input = json.loads(hidden_data)
    except json.JSONDecodeError:
        pdf_input = {}
        
    email = pdf_input.get("email", "User")
    
    print("\n" + "="*40)
    print(f"RECEIVED DATA FROM PDF!")
    print(f"Email: {email}")
    print(f"Timestamp: {pdf_input.get('timestamp', 'Unknown')}")
    print("="*40 + "\n")
    
    # 2. Server-side logic (call external APIs, validate data, etc.)
    prompt = pdf_input.get("prompt", "Tell me a joke")
    
    api_key = GROQ_API_KEY
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    
    import urllib.request
    import urllib.error
    
    req_data = json.dumps({
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")
    
    req = urllib.request.Request(groq_url, data=req_data, headers={
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
    })
    
    try:
        with urllib.request.urlopen(req) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            reply = resp_data["choices"][0]["message"]["content"]
            status = "Success"
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        reply = f"HTTP Error {e.code}: {error_body}"
        status = "Error"
    except Exception as e:
        reply = f"Error: {e}"
        status = "Error"
        
    # Escape special FDF string characters
    reply_fdf = str(reply).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)').replace('\r', ' ').replace('\n', ' ')
    
    api_results = {
        "status": status,
        "message": reply_fdf[:500], # FDF can be finicky with very long strings, limit slightly
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # 3. Construct the FDF payload
    # Note: The strings in /T MUST exactly match the names of the text fields in your PDF.
    fdf_payload = f"""%FDF-1.2
1 0 obj
<<
/FDF <<
    /Fields [
        << /T (StatusField) /V ({api_results['status']}) >>
        << /T (ApiResponse) /V ({api_results['message']}) >>
        << /T (DateSlot) /V ({api_results['date']}) >>
    ]
>>
>>
endobj
trailer
<< /Root 1 0 R >>
%%EOF"""

    # 4. Critical: Send back the FDF with the exact MIME type required by viewers
    return Response(fdf_payload, mimetype='application/vnd.fdf')

def clean_markdown(text):
    """
    Strips or converts common markdown to plain text for better PDF display.
    """
    # Remove bold/italic **text** or *text*
    text = re.sub(r'\*\*+(.*?)\*\*+', r'\1', text)
    text = re.sub(r'\*+(.*?)\*+', r'\1', text)
    # Remove headers ### Header
    text = re.sub(r'#+\s*(.*?)\n', r'\1\n', text)
    # Ensure bullet points are clean
    text = text.replace(' - ', ' • ')
    return text.strip()

@app.route('/generate-rag-fdf', methods=['POST'])
def generate_rag_fdf():
    """
    Acts as a RAG proxy. Receives a user's prompt and pre-retrieved context
    from the PDF's local TF-IDF engine, sends it to the LLM, and returns FDF.
    """
    hidden_data = request.form.get('HiddenJSONData', "{}")
    try:
        pdf_input = json.loads(hidden_data)
    except json.JSONDecodeError:
        pdf_input = {}
        
    prompt = pdf_input.get("prompt", "")
    context = pdf_input.get("context", "")
    
    print("\n" + "="*40)
    print(f"RECEIVED RAG DATA FROM RESUME PDF!")
    print(f"Prompt: {prompt}")
    print(f"Context Length: {len(context)} chars")
    print("="*40 + "\n")
    
    # GROQ_API_KEY is loaded globally from environment
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    
    import urllib.request
    import urllib.error
    
    system_prompt = (
        "You are an AI assistant answering questions about Naresh's resume. "
        "Use ONLY the following context to answer the user's question. "
        "IMPORTANT: Format your response for a plain text viewer. Do not use Markdown like **bold** or ### headers. "
        "Use clear bullet points and double newlines between paragraphs for readability. "
        "Keep the answer concise and professional.\n\n"
        f"CONTEXT:\n{context}"
    )
    
    req_data = json.dumps({
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    }).encode("utf-8")
    
    req = urllib.request.Request(groq_url, data=req_data, headers={
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
    })
    
    try:
        with urllib.request.urlopen(req) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            reply = resp_data["choices"][0]["message"]["content"]
            status = "Success"
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        reply = f"HTTP Error {e.code}: {error_body}"
        status = "Error"
    except Exception as e:
        reply = f"Error: {e}"
        status = "Error"
        
    # Clean markdown and prepare for FDF
    reply_cleaned = clean_markdown(reply)
    
    # Escape special FDF string characters
    # We replace \n with \r because PDF fields usually use \r for line breaks.
    # We DO NOT replace \n with ' ' anymore!
    reply_fdf = reply_cleaned.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)').replace('\n', '\r')
    
    fdf_payload = f"""%FDF-1.2
1 0 obj
<<
/FDF <<
    /Fields [
        << /T (StatusField) /V ({status}) >>
        << /T (ApiResponse) /V ({reply_fdf}) >>
    ]
>>
>>
endobj
trailer
<< /Root 1 0 R >>
%%EOF"""

    return Response(fdf_payload, mimetype='application/vnd.fdf')

@app.route('/track-open', methods=['GET'])
def track_open():
    """
    Passive endpoint that logs when a document is opened.
    Driven by the PDF's /OpenAction -> /URI dictionary.
    """
    ip_address = request.remote_addr
    user_agent = request.headers.get('User-Agent', 'Unknown')
    
    print("\n" + "*"*40)
    print("🚨 PDF OPENED (ZERO-CLICK TRACKING) 🚨")
    print(f"IP: {ip_address}")
    print(f"Browser Details: {user_agent}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("*"*40 + "\n")
    
    # Return a tiny 1x1 transparent pixel or a simple OK response.
    # The browser/PDF viewer expects *something* back from the GET request.
    return "OK", 200

if __name__ == '__main__':
    print("Starting purely Python PDF Proxy on port 3000...")
    print("Endpoint: POST http://localhost:3000/generate-fdf")
    app.run(port=3000, debug=True)
