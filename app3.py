import os

from app_core import create_app

app = create_app()


def configure_runtime():
    os.environ.setdefault('OMP_NUM_THREADS', '2')
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')


if __name__ == '__main__':
    configure_runtime()
    app.run(host='0.0.0.0', port=5500, debug=True, threaded=True)
