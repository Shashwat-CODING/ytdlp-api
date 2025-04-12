from flask import Flask, jsonify, request
from flask_cors import CORS
import yt_dlp
import os
import logging
import threading
import time
import requests
import json

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all origins

@app.route('/rv/<video_id>')
def get_audio_stream(video_id):
    try:
        logger.info(f"Processing request for video ID: {video_id}")
        
        # Set up yt-dlp options with better error handling and updated settings
        ydl_opts = {
            'format': 'bestaudio/best',
            'cookiefile': 'cookies.txt',
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': True,
            'skip_download': True,
            'extractor_retries': 3,       # Retry extraction 3 times
            'socket_timeout': 30,         # Increase timeout
            'nocheckcertificate': True,   # Skip HTTPS certificate validation
            'geo_bypass': True,           # Try to bypass geo-restrictions
            'allow_unplayable_formats': True, # Try to get info even for unplayable formats
            'playlist_items': '1',        # In case the URL is a playlist, only get first item
        }
        
        # Get video info
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                # Try to update yt-dlp first (this requires yt-dlp to be installed with pip)
                try:
                    import subprocess
                    subprocess.run(["python", "-m", "pip", "install", "--upgrade", "yt-dlp"], 
                                   capture_output=True, text=True, timeout=30)
                    logger.info("Updated yt-dlp to latest version")
                except Exception as e:
                    logger.warning(f"Could not update yt-dlp: {str(e)}")
                
                # Log cookie file status
                if os.path.exists('cookies.txt'):
                    logger.info(f"cookies.txt exists, size: {os.path.getsize('cookies.txt')} bytes")
                else:
                    logger.warning("cookies.txt does not exist")
                    
                # Extract info with verbose error handling
                try:
                    info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                except Exception as e:
                    logger.error(f"Extract info error details: {str(e)}")
                    # Try alternate URL format
                    logger.info("Trying alternate URL format...")
                    info = ydl.extract_info(f'youtu.be/{video_id}', download=False)
                
                # Check if we got any info at all
                if info is None:
                    logger.error("No video information returned from yt-dlp")
                    # Try another extractor option as fallback
                    ydl_opts['force_generic_extractor'] = True
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                        logger.info("Attempting fallback with generic extractor...")
                        info = ydl2.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                        if info is None:
                            return jsonify({'error': 'Could not retrieve video information after multiple attempts'}), 404
                
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
                format_note = ''
                format_id = ''
                acodec = 'unknown'
                
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
                        audio_formats.sort(key=lambda x: x.get('tbr', 0) if x.get('tbr') is not None else 0, reverse=True)
                        best_format = audio_formats[0]
                        audio_url = best_format['url']
                        format_note = best_format.get('format_note', '')
                        format_id = best_format.get('format_id', '')
                        acodec = best_format.get('acodec', 'unknown')
                
                if not audio_url:
                    # Log more details about available formats
                    logger.error(f"No audio URL found. Available formats: {json.dumps(info.get('formats', []), indent=2)}")
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
                error_message = str(e)
                logger.error(f"yt-dlp download error: {error_message}")
                
                # Try to provide more helpful errors
                if "Video unavailable" in error_message:
                    return jsonify({'error': 'This video is unavailable or private'}), 404
                elif "sign in to" in error_message.lower() or "log in to" in error_message.lower():
                    return jsonify({'error': 'This video requires authentication. Your cookies.txt may be outdated'}), 403
                elif "copyright" in error_message.lower():
                    return jsonify({'error': 'This video is not available due to copyright restrictions'}), 403
                elif "geo-restricted" in error_message.lower():
                    return jsonify({'error': 'This video is geo-restricted and not available in the server region'}), 451
                else:
                    return jsonify({'error': error_message}), 500
                
    except Exception as e:
        logger.exception(f"Unexpected error: {str(e)}")
        return jsonify({'error': f"Server error: {str(e)}"}), 500

# Format listing endpoint for debugging
@app.route('/formats/<video_id>')
def list_formats(video_id):
    try:
        ydl_opts = {
            'cookiefile': 'cookies.txt',
            'quiet': True,
            'ignoreerrors': True,
            'nocheckcertificate': True,
            'geo_bypass': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
            except Exception as e:
                logger.error(f"Format listing extraction error: {str(e)}")
                return jsonify({'error': str(e)}), 500
            
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
        logger.exception(f"Format listing error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Add a debugging endpoint for cookies status
@app.route('/debug/cookies')
def check_cookies():
    try:
        if not os.path.exists('cookies.txt'):
            return jsonify({'status': 'error', 'message': 'cookies.txt file does not exist'})
        
        file_size = os.path.getsize('cookies.txt')
        if file_size == 0:
            return jsonify({'status': 'warning', 'message': 'cookies.txt exists but is empty'})
        
        # Read first few lines to check format (without exposing sensitive data)
        with open('cookies.txt', 'r') as f:
            first_line = f.readline().strip()
            has_content = len(first_line) > 0
            looks_like_netscape = first_line.startswith('# Netscape')
        
        return jsonify({
            'status': 'ok',
            'file_exists': True,
            'file_size_bytes': file_size,
            'has_content': has_content,
            'appears_valid': looks_like_netscape
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Add a basic health check route
@app.route('/')
def index():
    return jsonify({
        'status': 'API is running',
        'yt_dlp_version': yt_dlp.version.__version__,
        'endpoints': {
            '/rv/<video_id>': 'Get audio stream URL',
            '/formats/<video_id>': 'List all available formats',
            '/debug/cookies': 'Check cookies.txt status',
        }
    })

# Function to ping the server every 14 minutes to prevent Render from spinning down
def keep_alive():
    app_url = "https://ytdlp-api-ox2d.onrender.com/"
    logger.info(f"Starting self-ping service to {app_url}")
    
    while True:
        try:
            time.sleep(14 * 60)  # 14 minutes
            logger.info("Sending self-ping request")
            requests.get(app_url)
        except Exception as e:
            logger.error(f"Self-ping error: {str(e)}")

if __name__ == '__main__':
    # Check if cookies.txt exists, if not create an empty file
    if not os.path.exists('cookies.txt'):
        open('cookies.txt', 'w').close()
        logger.warning("Created empty cookies.txt file")
    else:
        logger.info(f"Found existing cookies.txt, size: {os.path.getsize('cookies.txt')} bytes")
    
    # Start the keep-alive thread
    keep_alive_thread = threading.Thread(target=keep_alive)
    keep_alive_thread.daemon = True
    keep_alive_thread.start()
    logger.info("Started keep-alive thread to prevent Render from spinning down")
        
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
