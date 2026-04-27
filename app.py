from flask import Flask, request, jsonify, render_template
from scripts.check_driving_distance import within_driving_threshold
from dotenv import load_dotenv
import os

load_dotenv()  # loads .env from current working directory

app = Flask(__name__)


@app.route('/')
def index():
    # Simple UI to call the API (for humans)
    return render_template('index.html')


@app.route('/api/check', methods=['GET', 'POST'])
def api_check():
    """API endpoint to check driving distance.

    GET params: my_suburb, work_suburb, distance_threshold (km)
    POST JSON: {"my_suburb": "...", "work_suburb": "...", "distance_threshold": 15}

    Returns JSON: {within: bool, distance_km: float|null, method: str|null, error: str|null}
    """
    data = {}
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
    else:
        data = request.args.to_dict()

    my_suburb = data.get('my_suburb')
    work_suburb = data.get('work_suburb')
    threshold = data.get('distance_threshold')

    if threshold is None:
        threshold = 15
    try:
        threshold = float(threshold)
    except Exception:
        return jsonify({'within': False, 'distance_km': None, 'method': None, 'error': 'invalid threshold'}), 400

    if not my_suburb or not work_suburb:
        return jsonify({'within': False, 'distance_km': None, 'method': None, 'error': 'missing suburb parameters'}), 400

    try:
        within, dist_km, method = within_driving_threshold(my_suburb, work_suburb, threshold)
        return jsonify({'within': bool(within), 'distance_km': None if dist_km is None else float(dist_km), 'method': method, 'error': None})
    except Exception as e:
        return jsonify({'within': False, 'distance_km': None, 'method': None, 'error': str(e)}), 500


# if __name__ == '__main__':
#     app.config['TEMPLATES_AUTO_RELOAD'] = True
#     app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=True)
