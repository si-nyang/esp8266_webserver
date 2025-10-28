from flask import Flask, render_template
import os
import sys

app = Flask(__name__)

if 'SESSION_SECRET' not in os.environ:
    print("ERROR: SESSION_SECRET environment variable is not set!", file=sys.stderr)
    print("Please set SESSION_SECRET to a secure random value.", file=sys.stderr)
    sys.exit(1)

app.secret_key = os.environ['SESSION_SECRET']

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
