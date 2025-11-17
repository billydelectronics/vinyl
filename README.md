Vinyl Collection Web App

A full-stack web application for tracking a personal vinyl record collection. The project uses SvelteKit, Tailwind CSS, TypeScript, Python, and Docker, and is hosted on a Mac mini on a home network.

⸻

🚀 Features
	•	Track and manage a vinyl collection of any size
	•	SvelteKit front-end with fast, reactive UI
	•	Tailwind CSS for modern styling
	•	Python backend for data processing and API logic
	•	Dockerized environment for consistent deployment
	•	Runs locally on macOS hardware (Mac mini)
	•	SSH-enabled GitHub repo for version control

⸻

🧱 Project Structure

vinyl/
├── app/                 # Python backend
├── src/                 # SvelteKit front-end
├── static/              # Static assets
├── start-vinyl.sh       # Startup script
├── stop-vinyl.sh        # Shutdown script
├── Dockerfile           # Docker build instructions
├── docker-compose.yml   # Multi-container setup
└── README.md            # Project documentation


⸻

📦 Requirements

Make sure you have the following installed:
	•	Node.js (latest LTS recommended)
	•	Python 3.x
	•	Docker & Docker Compose
	•	Git (using SSH)

⸻

🛠️ Development Setup

1. Clone the Repository

git clone git@github.com:billydelectronics/vinyl_svelte_tailwind.git
cd vinyl_svelte_tailwind

2. Install Frontend Dependencies

npm install

3. Install Backend Dependencies

Create a virtual environment:

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt


⸻

🧪 Running the App (Development)

Run the SvelteKit Dev Server

npm run dev

This will start the front-end UI with hot-reload.

Run the Python Backend

Inside the app/ directory:

python3 main.py


⸻

🐳 Running with Docker (Production)

On your Mac mini or any host server:

docker compose down
docker compose up --build -d

This builds all images and runs the stack in detached mode.

⸻

🔄 Deploying Updates

When you push new code:

git pull
docker compose down
docker compose up --build -d

You can also automate this with a script.

⸻

🗂️ Version Control (Using SSH)

Your repository uses SSH authentication. To push changes:

git add .
git commit -m "Your message"
git push


⸻

🧭 Roadmap / Future Enhancements
	•	Add album artwork support
	•	Add Discogs API integration
	•	User authentication (for multiple collectors)
	•	Import/export collection
	•	Stats dashboard (total value, genres, decades)

⸻

📝 License

This project is for personal use but feel free to adapt or fork it.

⸻

👤 Author

Billy D
GitHub: billydelectronics￼