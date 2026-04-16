# Alvea

Système multi-agents d'orchestration de développement logiciel piloté par IA. Alvea décompose un objectif en langage naturel en tâches atomiques, puis les exécute via un pipeline d'agents spécialisés : planification, génération de code, revue et exécution.

## Agents

| Agent | Rôle |
|-------|------|
| **Jef** | Planificateur — décompose l'objectif en tâches atomiques |
| **Derick** | Orchestrateur — priorise et dispatche les tâches |
| **Zed** | Codeur — génère le code via LLM |
| **Earl** | Relecteur — valide la qualité du code produit |
| **Chris** | Exécuteur — lance les commandes et vérifie les sorties |

Pipeline d'exécution : `Objectif → Jef → Derick → Zed → Earl → Chris → workspace/`

## Prérequis

- Python 3.12+
- Un serveur LLM local compatible OpenAI (ex. [Ollama](https://ollama.com), LM Studio)

## Installation

```bash
git clone <repo>
cd alvea

python -m venv .venv
source .venv/Scripts/activate  # Windows
# source .venv/bin/activate    # Unix/macOS

pip install openai
```

## Utilisation

### CLI

```bash
python main.py "Crée une API REST FastAPI avec des endpoints CRUD pour un modèle User"
```

### Interface graphique

```bash
python gui.py
```

La GUI permet de configurer l'architecture, les composants (Docker, tests, lint…), la base de données et le modèle LLM avant de lancer les agents.

## Configuration

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `llm_url` | `http://localhost:11434/v1` | URL du serveur LLM |
| `llm_model` | `llama3` | Modèle à utiliser |
| `max_cycles` | `20` | Nombre maximum de cycles d'orchestration |

Les contraintes de qualité (architecture, patterns interdits, règles par agent) sont définies dans `vision/vision.json`.

## Structure du projet

```
alvea/
├── agents/              # Les cinq agents (base_agent + jef, derick, zed, earl, chris)
├── core/                # Bus d'événements, client LLM, gestionnaire de tâches, moteur de planification
├── plan/                # État d'exécution (plan.json)
├── tasks/               # Backlog de tâches (tasks.json)
├── runtime/             # État global et journal d'événements (events.log)
├── vision/              # Contraintes de qualité (vision.json)
├── workspace/           # Code généré par les agents
├── main.py              # Point d'entrée CLI
└── gui.py               # Interface graphique Tkinter
```

## État et persistance

Alvea persiste son état en JSON pour permettre reprise et audit :

- `tasks/tasks.json` — backlog de toutes les tâches
- `plan/plan.json` — file d'exécution, historique des décisions, métriques
- `runtime/state.json` — statut global du moteur et des agents
- `runtime/events.log` — journal JSONL immuable de tous les événements

## Scoring des tâches

Derick score chaque tâche avant de l'admettre dans la file d'exécution :

```
score = (priority_hint × 0.4) + (vision_alignment × 0.4) + ((1 - complexity) × 0.2)
```

Seuil d'admission par défaut : `0.65`
