from flask import Flask, jsonify, request
from flask_cors import CORS
import yt_dlp
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all origins

@app.route('/rv/<video_id>')
def get_audio_stream(video_id):
    try:
        logger.info(f"Processing request for video ID: {video_id}")
        
        # Set up yt-dlp options with more flexibility
        ydl_opts = {
            'format': 'bestaudio/best',  # Try audio, fallback to any format
            'cookiefile': 'cookies.txt',
            'quiet': False,  # We want to see the output for debugging
            'no_warnings': False,
            'ignoreerrors': True,  # Continue even if there are non-fatal errors
        }
        
        # Get video info
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                
                # Check if we got any info at all
                if info is None:
                    return jsonify({'error': 'Could not retrieve video information'}), 404
                
                # Check if this is an image-only post
                if 'formats' in info and len(info['formats']) > 0:
                    # Check if any format has audio
                    has_audio = any(f.get('acodec', 'none') != 'none' for f in info['formats'])
                    if not has_audio:
                        return jsonify({
                            'error': 'This YouTube content has no audio streams',
                            'title': info.get('title', 'Unknown Title'),
                            'type': 'image_only'
                        }), 200
                
                # Get the title
                title = info.get('title', 'Unknown Title')
                
                # Try to get the audio URL
                audio_url = None
                
                # First check requested formats (for adaptive streams)
                if 'requested_formats' in info:
                    for fmt in info['requested_formats']:
                        if fmt.get('acodec', 'none') != 'none':
                            audio_url = fmt['url']
                            format_note = fmt.get('format_note', '')
                            format_id = fmt.get('format_id', '')
                            acodec = fmt.get('acodec', 'unknown')
                            break
                
                # If no URL found, try the direct URL
                if not audio_url and 'url' in info:
                    audio_url = info['url']
                    format_note = info.get('format_note', '')
                    format_id = info.get('format_id', '')
                    acodec = info.get('acodec', 'unknown')
                
                # If still no URL, check all formats
                if not audio_url and 'formats' in info:
                    # First try to find formats with audio
                    audio_formats = [f for f in info['formats'] if f.get('acodec', 'none') != 'none']
                    
                    if audio_formats:
                        # Sort by quality (assuming higher tbr means better quality)
                        audio_formats.sort(key=lambda x: x.get('tbr', 0), reverse=True)
                        best_format = audio_formats[0]
                        audio_url = best_format['url']
                        format_note = best_format.get('format_note', '')
                        format_id = best_format.get('format_id', '')
                        acodec = best_format.get('acodec', 'unknown')
                
                if not audio_url:
                    return jsonify({'error': 'No audio URL found in any format'}), 404
                
                # Success! Return the URL and title
                response = {
                    'url': audio_url,
                    'title': title,
                    'format_note': format_note,
                    'format_id': format_id,
                    'acodec': acodec
                }
                
                return jsonify(response)
                
            except yt_dlp.utils.DownloadError as e:
                logger.error(f"yt-dlp download error: {str(e)}")
                return jsonify({'error': str(e)}), 500
                
    except Exception as e:
        logger.exception(f"Unexpected error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Format listing endpoint for debugging
@app.route('/formats/<video_id>')
def list_formats(video_id):
    try:
        ydl_opts = {
            'cookiefile': 'cookies.txt',
            'quiet': True,
            'ignoreerrors': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
            
            if info is None:
                return jsonify({'error': 'Could not retrieve video information'}), 404
                
            formats = []
            for f in info.get('formats', []):
                formats.append({
                    'format_id': f.get('format_id'),
                    'ext': f.get('ext'),
                    'acodec': f.get('acodec'),
                    'vcodec': f.get('vcodec'),
                    'tbr': f.get('tbr'),
                    'format_note': f.get('format_note', '')
                })
                
            return jsonify({
                'title': info.get('title'),
                'formats': formats,
                'has_audio': any(f.get('acodec', 'none') != 'none' for f in info.get('formats', []))
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Add a test route
@app.route('/')
def index():
    return jsonify({
        'status': 'API is running',
        'endpoints': {
            '/rv/<video_id>': 'Get audio stream URL',
            '/formats/<video_id>': 'List all available formats',
        }
    })

if __name__ == '__main__':
    # Check if cookies.txt exists, if not create an empty file
    if not os.path.exists('cookies.txt'):
        open('cookies.txt', 'w').close()
        print("Created empty cookies.txt file")
        
    app.run(host='0.0.0.0', port=5000, debug=True)
