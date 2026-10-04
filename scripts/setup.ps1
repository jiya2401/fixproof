$ErrorActionPreference = "Stop"

Write-Host "Setting up FixProof backend..."
Set-Location "$PSScriptRoot\..\backend"
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt

Write-Host "Setting up FixProof frontend..."
Set-Location "$PSScriptRoot\..\frontend"
npm install

Write-Host "Setup complete."
Write-Host "Backend: cd backend; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port 8000"
Write-Host "Frontend: cd frontend; npm run dev"
