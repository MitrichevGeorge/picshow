rm -rf ~/.sqrv
git clone --depth 1 https://github.com/MitrichevGeorge/picshow.git ~/.sqrv
cd ~/.sqrv
python -m venv e
source e/bin/activate
pip install flask pillow PyQt5
python main.py &
ssh -R 80:localhost:8080 serveo.net > /tmp/serveo 2>&1 & sleep 5 && curl qrenco.de/$(cat /tmp/serveo)
