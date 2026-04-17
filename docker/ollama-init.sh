#!/bin/sh
set -e

echo "[ollama-init] Démarrage d'Ollama en arrière-plan..."
ollama serve &
OLLAMA_PID=$!

echo "[ollama-init] Attente du démarrage d'Ollama..."
until ollama list > /dev/null 2>&1; do
    sleep 2
done

echo "[ollama-init] Ollama prêt."

MODEL="${OLLAMA_MODEL:-llama3}"

if ollama list 2>/dev/null | grep -q "${MODEL}"; then
    echo "[ollama-init] Modèle '${MODEL}' déjà présent — rien à faire."
else
    echo "[ollama-init] Téléchargement de '${MODEL}'..."
    ollama pull "${MODEL}"
    echo "[ollama-init] '${MODEL}' téléchargé avec succès."
fi

kill $OLLAMA_PID
wait $OLLAMA_PID 2>/dev/null || true
echo "[ollama-init] Terminé."
