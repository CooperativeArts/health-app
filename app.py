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
        # Just list what files we find
        files = os.listdir('docs')
        return f"Found these files: {files}"
    except Exception as e:
        return f"Error: {str(e)}"
        
        if not documents:
            return "No documents were successfully loaded. Please check the docs folder."

        print(f"Number of documents loaded: {len(documents)}")
        
        text_splitter = CharacterTextSplitter(chunk_size=200, chunk_overlap=20)
        texts = text_splitter.split_documents(documents)
        print(f"Split into {len(texts)} chunks")
        
        embeddings = OpenAIEmbeddings()
        db = FAISS.from_documents(texts, embeddings)
        qa = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=db.as_retriever())
        
        print(f"Processing query: {user_query}")
        response = qa.run(user_query)
        print(f"Got response: {response}")
        
        return response if response else "No answer found. Please try rephrasing your question."
    except Exception as e:
        print(f"Main error: {str(e)}")
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)