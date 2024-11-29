from flask import Flask
from langchain.chat_models import ChatOpenAI
from langchain.schema import HumanMessage
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
llm = ChatOpenAI(temperature=0)

@app.route('/')
def hello():
    return 'Hello, World!'

@app.route('/test')
def test():
    try:
        response = llm.predict("Say hello!")
        return f"OpenAI through LangChain is working! Response: {response}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)