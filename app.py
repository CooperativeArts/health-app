from flask import Flask, request, render_template_string
import openai
import os
from dotenv import load_dotenv
import time

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
        
        # Read all documents first
        all_content = []
        files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
        
        for file in files:
            try:
                reader = PdfReader(f'docs/{file}')
                file_text = f"\nFrom {file}:\n"
                for page in reader.pages:
                    file_text += page.extract_text() + "\n"
                all_content.append(file_text)
            except Exception as e:
                continue

        # Combine all content and split into smaller chunks
        combined_text = "".join(all_content)
        chunk_size = 4000  # Smaller chunks
        chunks = [combined_text[i:i+chunk_size] for i in range(0, len(combined_text), chunk_size)]
        
        # Process first few chunks
        all_responses = []
        for chunk in chunks[:3]:  # Limit to first 3 chunks
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are analyzing documents. Always mention which documents contain the information you find."},
                    {"role": "user", "content": f"Based on this text:\n{chunk}\n\nQuestion: {user_question}"}
                ],
                temperature=0
            )
            all_responses.append(response.choices[0].message['content'])

        return "\n\nCombined findings:\n\n" + "\n".join(all_responses)
        
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)