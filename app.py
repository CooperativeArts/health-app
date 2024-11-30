from flask import Flask, request
from langchain.chat_models import ChatOpenAI
from langchain.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from langchain.chains import RetrievalQA
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
llm = ChatOpenAI()

@app.route('/query')
def query():
    try:
        user_query = request.args.get('q', 'What is this document about?')
        
        loader = TextLoader('docs/test.txt')
        documents = loader.load()
        text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        texts = text_splitter.split_documents(documents)
        embeddings = OpenAIEmbeddings()
        db = FAISS.from_documents(texts, embeddings)
        
        qa = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=db.as_retriever())
        response = qa.run(user_query)
        
        return f"Q: {user_query}\nA: {response}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)