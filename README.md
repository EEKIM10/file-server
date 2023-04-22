# File server


```bash
$ git clone https://github.com/EEKIM10/file-server.git
$ cd file-server
$ cp config.example.ini config.ini
$ pip install -r requirements.txt
$ python3 -m main.py
```

## Configuration
All options are in [config.example.ini](config.example.ini).

## Security
This is a very basic file server, similar to the autoindex provided by nginx.
Security is not exactly the highest concern. As such, this is left to other systems:

1. Use a reverse proxy to handle SSL and authentication.
2. Filesystem permissions

An example security config with nginx would be as such:
```
server {
    listen 80;
    server_name _;
    
    location / {
        auth_basic "File Server";
        auth_basic_user_file /etc/nginx/.htpasswd;
        # Generate with: htpasswd -c /etc/nginx/.htpasswd <username>
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

and then protecting files with filesystem permissions:
```
$ chmod 700 /path/to/file
```
(makes the file only readable by the owner)
