# Reed

Semantic Scholar paper recommendations based on Zotero library.

**Note:** This project is not affiliated with Semantic Scholar. By providing your [API key](https://www.semanticscholar.org/product/api#api-key), recommendations provided in the app will be based on the Semantic Scholar [recommendations API](https://api.semanticscholar.org/api-docs/recommendations).

## Showcase

> The app is live and hosted on Vercel: [reed.vercel.app](https://reed.vercel.app)

https://github.com/user-attachments/assets/086ad67a-6a34-48d1-b49b-74bc6a672e17

## Setup

Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:
```bash
pip install -r requirements.txt
```

Start the application:
```bash
npm i -g vercel # install Vercel CLI
vercel link # link to Vercel project
vercel env pull # pull environment variables
vercel dev # start deployment server
```
