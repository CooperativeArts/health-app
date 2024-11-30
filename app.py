from flask import Flask
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

@app.route('/test')
def test():
    try:
        # Load and process document
        loader = TextLoader('docs/test.txt')
        documents = loader.load()
        
        text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        texts = text_splitter.split_documents(documents)
        
        embeddings = OpenAIEmbeddings()
        db = FAISS.from_documents(texts, embeddings)
        
        # Create QA chain
        qa = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=db.as_retriever()
        )
        
        # Ask a question
        query = "What is this document about?"
        result = qa.run(query)
        
        return f"Question: {query}\nAnswer: {result}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)