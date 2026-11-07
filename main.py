from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app) # Yeh aapki website ko API use karne ki permission dega

@app.route('/api/fetch', methods=['GET'])
def fetch_video():
    url = request.args.get('url')
    if not url:
        return jsonify({"success": False, "error": "URL missing"}), 400

    ydl_opts = {
        'quiet': True,
        'format': 'best',
        'noplaylist': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            return jsonify({
                "success": True,
                "title": info.get('title', 'Video'),
                "thumbnail": info.get('thumbnail', ''),
                "download_url": info.get('url', '')
            })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
