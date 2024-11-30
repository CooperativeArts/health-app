from flask import Flask
from langchain.chat_models import ChatOpenAI
from langchain.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
llm = ChatOpenAI()

@app.route('/test')
def test():
    try:
        # Load document
        loader = TextLoader('docs/test.txt')
        documents = loader.load()
        
        # Split text
        text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        texts = text_splitter.split_documents(documents)
        
        # Create embeddings
        embeddings = OpenAIEmbeddings()
        
        # Create vector store
        db = FAISS.from_documents(texts, embeddings)
        
        # Test query
        query = "What's in the document?"
        docs = db.similarity_search(query)
        
        return f"Document processed! First chunk: {docs[0].page_content}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)