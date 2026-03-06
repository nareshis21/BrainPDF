# RAG Inside PDF: Resume AI Assistant

This repository contains a full RAG (Retrieval-Augmented Generation) pipeline embedded directly within a PDF document. It allows users to chat with a resume through a professional AI interface without leaving the PDF viewer.

## 🚀 Features

- **Semantic Search**: Pure JavaScript TF-IDF engine embedded in the PDF for fast, local context retrieval.
- **Semantic Chunking**: Intelligent resume parsing that respects logical sections (Experience, Projects, Skills).
- **Groq AI Integration**: Handshake between the PDF and LLaMA 3.1 via a Python proxy server.
- **Premium UI**: Modern, dark-themed chat interface appended to the original resume.
- **Cloud Ready**: Configured for easy deployment to Vercel.

## 📁 Repository Structure

- `create_rag_pdf.py`: The PDF generator. It reads the resume, builds the index, and injects the JS/UI.
- `proxy_server.py`: The backend proxy that handles Groq API communication and FDF response generation.
- `requirements.txt`: Python dependencies for cloud/local environments.
- `vercel.json`: Deployment configuration for Vercel.
- `Naresh_Lahajal_resume.pdf`: The source resume used for testing.

## 🛠️ Getting Started

### 1. Local Setup
1. Install dependencies: `pip install flask flask-cors fitz pypdf python-dotenv`
2. Create/Update a `.env` file in the same directory as `proxy_server.py`.
3. Set your Groq API key in the `.env` file (`GROQ_API_KEY=your_key`).
4. Run the proxy: `python proxy_server.py`
5. Generate the interactive PDF: `python create_rag_pdf.py`
6. Open `Interactive_Resume_Chat.pdf` in **Adobe Acrobat**.

### 2. Cloud Deployment (Vercel)
1. Install Vercel CLI: `npm i -g vercel`
2. Deploy the proxy: `vercel`
3. **Important**: In the Vercel Dashboard, go to **Settings > Environment Variables** and add:
   - Key: `GROQ_API_KEY`
   - Value: `your_groq_api_key_here`
4. Re-deploy or Restart the project on Vercel to pick up the key.

### 🌟 The Final Step: Connecting PDF to Cloud
Once you have your Vercel URL (e.g. `https://my-rag-proxy.vercel.app`):
1. Open `create_rag_pdf.py`.
2. Find the line: `PROXY_URL = "http://localhost:3000/generate-rag-fdf"`
3. Change it to: `PROXY_URL = "https://your-app.vercel.app/generate-rag-fdf"`
4. Save and run `python create_rag_pdf.py` one last time.
5. Now your PDF is "live" and works globally!

## 📄 License
MIT
