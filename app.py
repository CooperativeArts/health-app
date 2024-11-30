from flask import Flask, request, render_template_string
from langchain.document_loaders import DirectoryLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from langchain.chains import RetrievalQA
from langchain.chat_models import ChatOpenAI
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
llm = ChatOpenAI()

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
   </style>
</head>
<body>
   <h1>Document Q&A</h1>
   <div id="chat-box"></div>
   <form id="chat-form">
       <input type="text" id="question" placeholder="Ask a question..." required>
       <button type="submit">Send</button>
   </form>
   <script>
       document.getElementById('chat-form').onsubmit = function(e) {
           e.preventDefault();
           var question = document.getElementById('question').value;
           fetch('/query?q=' + encodeURIComponent(question))
               .then(response => response.text())
               .then(answer => {
                   var chatBox = document.getElementById('chat-box');
                   chatBox.innerHTML += '<p><b>Q:</b> ' + question + '</p>';
                   chatBox.innerHTML += '<p><b>A:</b> ' + answer + '</p>';
                   chatBox.scrollTop = chatBox.scrollHeight;
                   document.getElementById('question').value = '';
               });
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
       user_query = request.args.get('q', 'What is this about?')
       loader = DirectoryLoader('docs', glob="**/*.[tp][xd][tf]")  # Matches .txt and .pdf
       documents = loader.load()
       text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
       texts = text_splitter.split_documents(documents)
       embeddings = OpenAIEmbeddings()
       db = FAISS.from_documents(texts, embeddings)
       qa = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=db.as_retriever())
       response = qa.run(user_query)
       return response
   except Exception as e:
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)