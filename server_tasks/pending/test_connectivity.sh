echo "=== Connectivity Test ==="
date
cd /opt/a-stock-sentinel && git log --oneline -3
echo "=== Python ==="
source venv/bin/activate
python3 -c "print('Python OK')"
echo "=== Done ==="
