#!/usr/bin/env python3
"""
Simple YouTube Video Uploader
- Upload from Google Drive OR GitHub direct links
- Schedule 6 months from upload date
- Track progress automatically
- GitHub Actions compatible
"""

import os
import sys
import json
import pickle
import requests
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

# Google API imports
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.auth.transport.requests import Request
except ImportError:
    print("📦 Installing required packages...")
    os.system(f"{sys.executable} -m pip install -q google-auth-oauthlib google-auth-httplib2 google-api-python-client gdown")
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.auth.transport.requests import Request

class YouTubeUploader:
    def __init__(self):
        print("\n" + "="*70)
        print("🎬 Simple YouTube Video Uploader")
        print("="*70)
        
        # Configuration
        self.schedule_time = "20:00"  # 8 PM
        self.schedule_gap_minutes = 15
        self.schedule_months_ahead = 6
        
        # Files
        self.token_file = "youtube_token.pickle"
        self.videos_file = "videos.txt"
        self.tracker_file = "tracker.json"
        
        # Initialize
        self.youtube = None
        self.tracker = {}
        
    def get_my_ip_info(self):
        """Get upload IP and location - Multiple fallback APIs"""
        
        # Try multiple IP detection services
        apis = [
            'https://api.ipify.org?format=json',
            'https://ifconfig.me/all.json',
            'https://ipinfo.io/json',
            'https://api.my-ip.io/ip.json',
            'http://ip-api.com/json/'
        ]
        
        ip_info = {
            'ip': 'Unknown',
            'city': 'Unknown',
            'region': 'Unknown',
            'country': 'Unknown',
            'org': 'Unknown'
        }
        
        # First, get IP address
        for api in apis[:2]:
            try:
                print(f"🔍 Checking IP from: {api.split('/')[2]}")
                response = requests.get(api, timeout=10)
                data = response.json()
                
                if 'ip' in data:
                    ip_info['ip'] = data['ip']
                    print(f"✅ IP detected: {ip_info['ip']}")
                    break
                elif 'ip_addr' in data:
                    ip_info['ip'] = data['ip_addr']
                    print(f"✅ IP detected: {ip_info['ip']}")
                    break
            except Exception as e:
                print(f"⚠️ Failed: {str(e)[:50]}")
                continue
        
        # Then, get location info
        if ip_info['ip'] != 'Unknown':
            try:
                print(f"🌍 Getting location info...")
                response = requests.get(f'http://ip-api.com/json/{ip_info["ip"]}', timeout=10)
                data = response.json()
                
                if data.get('status') == 'success':
                    ip_info['city'] = data.get('city', 'Unknown')
                    ip_info['region'] = data.get('regionName', 'Unknown')
                    ip_info['country'] = data.get('country', 'Unknown')
                    ip_info['org'] = data.get('isp', 'Unknown')
                    print(f"✅ Location: {ip_info['city']}, {ip_info['country']}")
            except Exception as e:
                print(f"⚠️ Location lookup failed: {str(e)[:50]}")
        
        return ip_info
    
    def authenticate(self):
        """Authenticate with YouTube API"""
        print("\n🔐 Authenticating...")
        
        if not os.path.exists(self.token_file):
            print(f"❌ Token file not found: {self.token_file}")
            print("💡 Please upload youtube_token.pickle to the repo")
            sys.exit(1)
        
        try:
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)
            
            # Refresh if expired
            if creds and creds.expired and creds.refresh_token:
                print("🔄 Refreshing token...")
                creds.refresh(Request())
                
                # Save refreshed token
                with open(self.token_file, 'wb') as token:
                    pickle.dump(creds, token)
            
            self.youtube = build('youtube', 'v3', credentials=creds)
            
            # Get channel info
            channel_response = self.youtube.channels().list(
                part='snippet',
                mine=True
            ).execute()
            
            if channel_response['items']:
                channel = channel_response['items'][0]
                channel_name = channel['snippet']['title']
                channel_id = channel['id']
                print(f"✅ Authenticated as: {channel_name}")
                print(f"📺 Channel ID: {channel_id}")
                return channel_id
            else:
                print("❌ No channel found")
                sys.exit(1)
                
        except Exception as e:
            print(f"❌ Authentication failed: {e}")
            sys.exit(1)
    
    def load_tracker(self, channel_id):
        """Load or create progress tracker"""
        if os.path.exists(self.tracker_file):
            with open(self.tracker_file, 'r') as f:
                self.tracker = json.load(f)
            print(f"\n📊 Progress loaded:")
            print(f"   Uploaded: {self.tracker.get('uploaded_count', 0)} videos")
            print(f"   Last run: {self.tracker.get('last_run_date', 'Never')}")
        else:
            self.tracker = {
                'channel_id': channel_id,
                'total_videos': 0,
                'uploaded_count': 0,
                'last_uploaded_index': -1,
                'last_run_date': None,
                'upload_history': []
            }
            print("\n📊 New tracker created")
    
    def save_tracker(self):
        """Save progress"""
        with open(self.tracker_file, 'w') as f:
            json.dump(self.tracker, f, indent=2)
    
    def load_video_links(self):
        """Load video links from videos.txt"""
        if not os.path.exists(self.videos_file):
            print(f"\n❌ {self.videos_file} not found!")
            print("💡 Create videos.txt with video links (one per line)")
            sys.exit(1)
        
        with open(self.videos_file, 'r') as f:
            links = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        
        self.tracker['total_videos'] = len(links)
        print(f"\n📋 Found {len(links)} video links")
        
        return links
    
    def is_github_link(self, url):
        """Check if URL is a GitHub direct download link"""
        return 'github.com' in url or 'githubusercontent.com' in url
    
    def extract_drive_file_id(self, url):
        """Extract file ID from Google Drive URL"""
        patterns = [
            r'/file/d/([a-zA-Z0-9_-]+)',
            r'id=([a-zA-Z0-9_-]+)',
            r'/d/([a-zA-Z0-9_-]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def download_from_github(self, github_url, index):
        """Download video directly from GitHub with proper progress display"""
        print(f"\n📥 Downloading from GitHub #{index + 1}...")
        print(f"   URL: {github_url[:80]}...")
        
        try:
            output = f"video_{index + 1}.mp4"
            
            # Start download with stream
            print("   Connecting...")
            response = requests.get(github_url, stream=True, timeout=30, allow_redirects=True)
            response.raise_for_status()
            
            # Get file size
            total_size = int(response.headers.get('content-length', 0))
            
            if total_size == 0:
                print("   ⚠️ Warning: Cannot determine file size")
            else:
                print(f"   File size: {total_size / (1024*1024):.2f} MB")
            
            # Download with clean progress bar
            print("   Downloading...")
            downloaded = 0
            chunk_size = 1024 * 1024  # 1MB chunks
            
            with open(output, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            downloaded_mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            # Clean single-line progress
                            print(f"   📊 {progress:.1f}% | {downloaded_mb:.1f}/{total_mb:.1f} MB", end='\r')
            
            print()  # New line after download
            
            # Verify download
            if not os.path.exists(output):
                print("   ❌ File not created")
                return None
            
            actual_size = os.path.getsize(output)
            size_mb = actual_size / (1024 * 1024)
            
            # Check if file is valid
            if size_mb < 0.5:  # Less than 500KB is suspicious
                print(f"   ❌ Download failed - file too small ({size_mb:.2f} MB)")
                os.remove(output)
                return None
            
            # Check if download was complete
            if total_size > 0 and actual_size < total_size * 0.95:  # Allow 5% margin
                print(f"   ⚠️ Warning: File might be incomplete")
                print(f"   Expected: {total_size/(1024*1024):.2f} MB, Got: {size_mb:.2f} MB")
            
            print(f"   ✅ Downloaded successfully: {size_mb:.1f} MB")
            return output
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Network error: {str(e)[:100]}")
            return None
        except Exception as e:
            print(f"   ❌ Download error: {str(e)[:100]}")
            return None
    
    def download_from_drive(self, drive_url, index):
        """Download video from Google Drive"""
        file_id = self.extract_drive_file_id(drive_url)
        
        if not file_id:
            print(f"❌ Invalid Drive URL: {drive_url[:50]}")
            return None
        
        print(f"\n📥 Downloading from Google Drive #{index + 1}...")
        print(f"   File ID: {file_id}")
        
        try:
            import gdown
            
            output = f"video_{index + 1}.mp4"
            url = f"https://drive.google.com/uc?id={file_id}"
            
            gdown.download(url, output, quiet=False, fuzzy=True)
            
            if os.path.exists(output):
                size_mb = os.path.getsize(output) / (1024 * 1024)
                
                if size_mb < 1:
                    print(f"❌ Download failed - file too small ({size_mb:.2f} MB)")
                    os.remove(output)
                    return None
                
                print(f"✅ Downloaded: {size_mb:.1f} MB")
                return output
            else:
                print("❌ Download failed")
                return None
                
        except Exception as e:
            print(f"❌ Download error: {e}")
            return None
    
    def download_video(self, url, index):
        """Download video from either GitHub or Google Drive"""
        if self.is_github_link(url):
            return self.download_from_github(url, index)
        else:
            return self.download_from_drive(url, index)
    
    def calculate_schedule_time(self, video_index):
        """Calculate schedule time (6 months from today + time)"""
        now = datetime.now()
        
        # Add 6 months
        schedule_date = now + timedelta(days=180)
        
        # Parse schedule time (20:00)
        hour, minute = map(int, self.schedule_time.split(':'))
        
        # Add gap for each video (0, 15, 30, 45, 60, 75... minutes)
        gap = video_index * self.schedule_gap_minutes
        minute += gap
        
        # Adjust hour and day if minutes overflow
        extra_hours = minute // 60
        minute = minute % 60
        hour += extra_hours
        
        extra_days = hour // 24
        hour = hour % 24
        
        schedule_datetime = schedule_date.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0
        ) + timedelta(days=extra_days)
        
        # Convert to ISO 8601 format (UTC)
        # Bangladesh is UTC+6, so subtract 6 hours
        utc_datetime = schedule_datetime - timedelta(hours=6)
        
        return utc_datetime.strftime('%Y-%m-%dT%H:%M:%S.000Z'), schedule_datetime
    
    def upload_video(self, video_path, video_index):
        """Upload video to YouTube"""
        
        # Get video title from filename
        title = Path(video_path).stem  # Remove .mp4 extension
        
        # Calculate schedule time
        schedule_time_utc, schedule_time_bd = self.calculate_schedule_time(video_index)
        
        print(f"\n📤 Uploading: {title}")
        print(f"📅 Schedule: {schedule_time_bd.strftime('%Y-%m-%d %I:%M %p')} BD Time")
        
        try:
            # Video metadata
            body = {
                'snippet': {
                    'title': title,
                    'description': '',  # Empty description
                    'tags': [],  # No tags
                    'categoryId': '22'  # People & Blogs
                },
                'status': {
                    'privacyStatus': 'private',  # Initially private
                    'publishAt': schedule_time_utc,  # Schedule time
                    'selfDeclaredMadeForKids': False
                }
            }
            
            # Upload
            media = MediaFileUpload(
                video_path,
                chunksize=50*1024*1024,  # 50MB chunks
                resumable=True
            )
            
            request = self.youtube.videos().insert(
                part='snippet,status',
                body=body,
                media_body=media
            )
            
            print("⏳ Uploading to YouTube...")
            
            response = None
            last_progress = -1
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    if progress != last_progress:  # Only print when progress changes
                        print(f"   📤 Upload Progress: {progress}%")
                        last_progress = progress
            
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            print(f"\n✅ Upload complete!")
            print(f"🔗 Video URL: {video_url}")
            print(f"📅 Will be published: {schedule_time_bd.strftime('%Y-%m-%d %I:%M %p')} BD")
            
            return {
                'video_id': video_id,
                'title': title,
                'url': video_url,
                'scheduled_time': schedule_time_bd.isoformat()
            }
            
        except Exception as e:
            print(f"\n❌ Upload failed: {e}")
            return None
    
    def run(self):
        """Main execution"""
        
        # Show IP info
        print("\n🌐 Upload Location Info:")
        ip_info = self.get_my_ip_info()
        print(f"   IP: {ip_info['ip']}")
        print(f"   Location: {ip_info['city']}, {ip_info['region']}, {ip_info['country']}")
        print(f"   ISP: {ip_info['org']}")
        
        # Authenticate
        channel_id = self.authenticate()
        
        # Load tracker
        self.load_tracker(channel_id)
        
        # Load video links
        video_links = self.load_video_links()
        
        # Calculate next videos to upload (ALL REMAINING VIDEOS)
        start_index = self.tracker['last_uploaded_index'] + 1
        
        if start_index >= len(video_links):
            print("\n🎉 All videos already uploaded!")
            print(f"   Total: {self.tracker['uploaded_count']} videos")
            return
        
        today_videos = video_links[start_index:]  # Get ALL remaining videos
        
        print(f"\n📋 Upload Plan:")
        print(f"   Videos to upload: {len(today_videos)}")
        print(f"   Starting from: #{start_index + 1}")
        print(f"   Already uploaded: {self.tracker['uploaded_count']}")
        
        # Auto-start (no YES/NO confirmation)
        print("\n" + "="*70)
        print("🚀 Starting upload process...")
        print("="*70)
        
        # Upload ALL videos
        upload_results = []
        failed_videos = []
        
        for i, video_url in enumerate(today_videos):
            actual_index = start_index + i
            
            print(f"\n{'='*70}")
            print(f"📹 Video {i + 1}/{len(today_videos)} (Total: #{actual_index + 1}/{len(video_links)})")
            print(f"{'='*70}")
            
            # Download (supports both GitHub and Google Drive)
            video_path = self.download_video(video_url, i)
            
            if not video_path:
                print("❌ Download failed - Skipping this video")
                failed_videos.append({
                    'index': actual_index + 1,
                    'url': video_url,
                    'reason': 'Download failed'
                })
                continue
            
            # Upload
            result = self.upload_video(video_path, i)
            
            if result:
                upload_results.append(result)
                self.tracker['uploaded_count'] += 1
                self.tracker['last_uploaded_index'] = actual_index
                print(f"✅ Video #{actual_index + 1} completed successfully")
            else:
                print(f"❌ Upload failed for video #{actual_index + 1}")
                failed_videos.append({
                    'index': actual_index + 1,
                    'url': video_url,
                    'reason': 'Upload failed'
                })
            
            # Cleanup
            try:
                if os.path.exists(video_path):
                    os.remove(video_path)
                    print(f"🗑️ Cleaned up temporary file")
            except Exception as e:
                print(f"⚠️ Cleanup warning: {e}")
        
        # Update tracker
        self.tracker['last_run_date'] = datetime.now().isoformat()
        self.tracker['upload_history'].append({
            'date': datetime.now().isoformat(),
            'videos': upload_results,
            'failed': failed_videos,
            'ip_info': ip_info
        })
        
        self.save_tracker()
        
        # Save detailed IP log
        ip_log_file = f"ip_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(ip_log_file, 'w') as f:
            f.write("="*70 + "\n")
            f.write(f"YouTube Upload Session - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*70 + "\n\n")
            f.write(f"IP Address: {ip_info['ip']}\n")
            f.write(f"City: {ip_info['city']}\n")
            f.write(f"Region: {ip_info['region']}\n")
            f.write(f"Country: {ip_info['country']}\n")
            f.write(f"ISP/Organization: {ip_info['org']}\n\n")
            f.write(f"Videos Uploaded: {len(upload_results)}\n")
            f.write(f"Videos Failed: {len(failed_videos)}\n")
            f.write(f"Total Progress: {self.tracker['uploaded_count']}/{self.tracker['total_videos']}\n\n")
            
            if failed_videos:
                f.write("="*70 + "\n")
                f.write("Failed Videos:\n")
                f.write("="*70 + "\n")
                for fail in failed_videos:
                    f.write(f"\n#{fail['index']} - {fail['reason']}\n")
                    f.write(f"   URL: {fail['url']}\n")
                f.write("\n")
            
            f.write("="*70 + "\n")
            f.write("Successfully Uploaded Videos:\n")
            f.write("="*70 + "\n")
            for i, video in enumerate(upload_results, 1):
                f.write(f"\n{i}. {video['title']}\n")
                f.write(f"   URL: {video['url']}\n")
                f.write(f"   Scheduled: {video['scheduled_time']}\n")
        
        print(f"\n💾 IP log saved: {ip_log_file}")
        
        # Summary
        print("\n" + "="*70)
        print("✅ Upload Session Complete!")
        print("="*70)
        print(f"📊 Session Stats:")
        print(f"   ✅ Uploaded: {len(upload_results)} videos")
        print(f"   ❌ Failed: {len(failed_videos)} videos")
        print(f"   📈 Total Progress: {self.tracker['uploaded_count']}/{self.tracker['total_videos']}")
        print(f"   📉 Remaining: {self.tracker['total_videos'] - self.tracker['uploaded_count']}")
        
        if failed_videos:
            print(f"\n❌ Failed Videos:")
            for fail in failed_videos:
                print(f"   #{fail['index']} - {fail['reason']}")
        
        print(f"\n🌐 Uploaded from:")
        print(f"   IP Address: {ip_info['ip']}")
        print(f"   Location: {ip_info['city']}, {ip_info['region']}")
        print(f"   Country: {ip_info['country']}")
        print(f"   ISP/Org: {ip_info['org']}")
        print(f"\n🔒 Security Check:")
        if 'Microsoft' in ip_info['org'] or 'GitHub' in ip_info['org'] or 'Azure' in ip_info['org']:
            print(f"   ✅ Upload from GitHub Server - Your IP is SAFE!")
        elif ip_info['org'] != 'Unknown':
            print(f"   ℹ️ Upload from: {ip_info['org']}")
        else:
            print(f"   ⚠️ Could not verify ISP")
        print("\n📅 All videos scheduled for 6 months from today")
        print("="*70)

def main():
    print("\n" + "="*70)
    print("🎬 YouTube Simple Video Uploader")
    print("="*70)
    print("✅ Upload from Google Drive OR GitHub")
    print("✅ Schedule 6 months ahead")
    print("✅ Auto progress tracking")
    print("✅ Upload ALL videos at once")
    print("✅ No confirmation needed")
    print("="*70)
    
    try:
        uploader = YouTubeUploader()
        uploader.run()
    except KeyboardInterrupt:
        print("\n\n⚠️ Cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
