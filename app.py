from flask import Flask, request, render_template_string
import openai
import os
from dotenv import load_dotenv

app = Flask(__name__)

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
        from pypdf import PdfReader
        
        load_dotenv()
        openai.api_key = os.getenv('OPENAI_API_KEY')
        
        user_question = request.args.get('q', '')
        files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
        
        all_text = ""
        max_chars = 30000  # Doubled the limit

        # First pass: Get first page of each document
        for file in files:
            try:
                reader = PdfReader(f'docs/{file}')
                if reader.pages:
                    first_page = reader.pages[0].extract_text()
                    all_text += f"\n=== Start of {file} ===\n"
                    all_text += f"[Page 1]: {first_page}\n"
                    
            except Exception as e:
                continue
        
        # If we have room, get more pages
        if len(all_text) < max_chars:
            for file in files:
                try:
                    reader = PdfReader(f'docs/{file}')
                    if len(reader.pages) > 1:
                        for i in range(1, min(3, len(reader.pages))):
                            page_text = reader.pages[i].extract_text()
                            if len(all_text) + len(page_text) < max_chars:
                                all_text += f"=== More from {file} ===\n"
                                all_text += f"[Page {i+1}]: {page_text}\n"
                            else:
                                break
                except Exception as e:
                    continue

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are analyzing PDF documents. Your task is to find and provide relevant information from these documents. Always mention which document and page number contains the information you reference."},
                {"role": "user", "content": f"Documents content:\n{all_text}\n\nQuestion: {user_question}"}
            ],
            temperature=0
        )
        
        return response.choices[0].message['content']
        
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)