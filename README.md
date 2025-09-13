Windows:
Just download MouseWalk.exe and launch it anywhere. The script will start without any additional downloads.

Linux:
1. Install python 3.10.0.
2. Download MouseWalkLinux folder.
3. Install requirements from requirements.txt
Debian/Ubuntu:
```bash
sudo apt update
sudo apt install -y libx11-6 libx11-dev libxss1 libxss-dev
```
Fedora:
```bash
sudo dnf install -y libX11 libX11-devel libXScrnSaver libXScrnSaver-devel
```

4. Launch script via main_linux.py.
```bash
python3 ./linux/main_linux.py --minutes 10
```
