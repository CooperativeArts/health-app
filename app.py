from flask import Flask, request, render_template_string
from langchain.document_loaders import TextLoader, PyPDFLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from langchain.chains import RetrievalQA
from langchain.chat_models import ChatOpenAI
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
llm = ChatOpenAI(temperature=0, request_timeout=30)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
   <title>RAG Chat</title>
   <style>
       body { max-width: 800px; margin: auto; padding: 20px; }
       #chat-box { height: 400px; border: 1px solid #ccc; overflow-y: scroll; margin: 20px 0; padding: 10px; }
       input[type="text"] { width: 80%; padding: 10px; }
       button { padding: 10px 20px; }
       .loading { color: #666; }
   </style>
</head>
<body>
   <h1>Document Q&A</h1>
   <div id="chat-box"></div>
   <form id="chat-form">
       <input type="text" id="question" placeholder="Ask a question..." required>
       <button type="submit" id="submit-btn">Send</button>
   </form>
   <script>
       document.getElementById('chat-form').onsubmit = async function(e) {
           e.preventDefault();
           const chatBox = document.getElementById('chat-box');
           const question = document.getElementById('question').value;
           const submitBtn = document.getElementById('submit-btn');
           
           submitBtn.disabled = true;
           chatBox.innerHTML += '<p><b>Q:</b> ' + question + '</p>';
           chatBox.innerHTML += '<p class="loading">Loading...</p>';
           chatBox.scrollTop = chatBox.scrollHeight;
           
           try {
               const response = await fetch('/query?q=' + encodeURIComponent(question));
               const answer = await response.text();
               chatBox.removeChild(chatBox.lastChild);
               chatBox.innerHTML += '<p><b>A:</b> ' + answer + '</p>';
           } catch (error) {
               chatBox.removeChild(chatBox.lastChild);
               chatBox.innerHTML += '<p style="color: red;"><b>Error:</b> ' + error.message + '</p>';
           } finally {
               submitBtn.disabled = false;
               document.getElementById('question').value = '';
               chatBox.scrollTop = chatBox.scrollHeight;
           }
       };
   </script>
</body>
</html>
'''

@app.route('/')
def home():
   return render_template_string(HTML_TEMPLATE)

@app.route('/query')
def query():
   try:
       # Try to read just the first PDF file as a test
       files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
       if not files:
           return "No PDF files found"
           
       # Try to read just the first file
       test_file = files[0]
       loader = PyPDFLoader(f'docs/{test_file}')
       pages = loader.load()
       
       # Return info about what we found
       return f"Successfully loaded {test_file}. First page preview: {pages[0].page_content[:500]}"
       
   except Exception as e:
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)