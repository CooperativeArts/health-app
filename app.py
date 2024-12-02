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
       
       app.logger.info("Starting query process")
       load_dotenv()
       openai.api_key = os.getenv('OPENAI_API_KEY')
       
       user_question = request.args.get('q', '')
       keywords = [word.lower() for word in user_question.split() if len(word) > 3]
       app.logger.info(f"Processing question: {user_question}")
       app.logger.info(f"Looking for keywords: {keywords}")
       
       files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
       app.logger.info(f"Found {len(files)} PDF files")
       
       relevant_content = []
       for file in files:
           try:
               app.logger.info(f"Scanning {file}")
               reader = PdfReader(f'docs/{file}')
               file_text = ""
               relevant_pages = []
               
               # First pass: identify relevant pages
               for page_num, page in enumerate(reader.pages):
                   page_text = page.extract_text()
                   if any(keyword in page_text.lower() for keyword in keywords):
                       relevant_pages.append((page_num, page_text))
               
               # If found relevant pages, add to content
               if relevant_pages:
                   content = {
                       "name": file,
                       "pages": relevant_pages,
                       "relevance_score": sum(1 for p in relevant_pages 
                                           for k in keywords 
                                           if k in p[1].lower())
                   }
                   relevant_content.append(content)
                   app.logger.info(f"Found relevant content in {file}")
               
           except Exception as e:
               app.logger.error(f"Error processing {file}: {str(e)}")
               continue
       
       # Sort documents by relevance score
       relevant_content.sort(key=lambda x: x['relevance_score'], reverse=True)
       
       # Combine content from most relevant documents
       combined_text = ""
       total_length = 0
       max_length = 6000  # Character limit for context
       
       for doc in relevant_content:
           doc_text = f"\nFrom {doc['name']}:\n"
           for _, page_text in doc['pages']:
               doc_text += page_text + "\n"
           
           if total_length + len(doc_text) > max_length:
               # If adding this document would exceed limit, skip it
               continue
               
           combined_text += doc_text
           total_length += len(doc_text)
       
       app.logger.info(f"Prepared {len(relevant_content)} relevant documents")
       
       response = openai.ChatCompletion.create(
           model="gpt-4",
           messages=[
               {"role": "system", "content": """You are a highly knowledgeable assistant analyzing documents about child safety, MARAM, and related topics. 
               Provide detailed, accurate answers and cite which specific documents contain the information you're referencing. 
               If information appears in multiple documents, mention all relevant sources. 
               If you can't find relevant information in the provided documents, say so."""},
               {"role": "user", "content": f"Based on these documents:\n{combined_text}\n\nQuestion: {user_question}\n\nProvide a comprehensive answer with document citations."}
           ],
           temperature=0
       )
       
       answer = response.choices[0].message['content']
       app.logger.info("Completed response")
       return answer
       
   except Exception as e:
       app.logger.error(f"Error occurred: {str(e)}")
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)