module.exports = {
  apps: [
    {
      name: 'pi-led-api',
      script: 'venv/bin/python3',
      args: '-m uvicorn main:app --host 0.0.0.0 --port 8080',
      cwd: __dirname,
      interpreter: 'none',
      watch: false,
      env: {
        NODE_ENV: 'production'
      }
    }
  ]
};
