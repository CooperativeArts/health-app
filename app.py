from flask import Flask
from langchain.chat_models import ChatOpenAI
from langchain.document_loaders import DirectoryLoader
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
llm = ChatOpenAI()

@app.route('/')
def hello():
    return 'Hello, World!'

@app.route('/test')
def test():
    try:
        # Test both LangChain and document loading
        loader = DirectoryLoader("docs", glob="**/*.txt")
        docs = loader.load()
        response = llm.predict("Say hello and tell me how many documents were loaded!")
        return f"LangChain loaded {len(docs)} documents. AI says: {response}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)