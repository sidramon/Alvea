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

```bash
python main.py
```

Ouvre automatiquement l'interface web sur `http://localhost:5000`. Le formulaire permet de configurer l'architecture, les composants (Docker, tests, lint…), la base de données et le modèle LLM avant de lancer les agents.

## Configuration

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `llm_url` | `http://localhost:11434/v1` | URL du serveur LLM |
| `llm_model` | `llama3` | Modèle à utiliser |
| `max_cycles` | `20` | Nombre maximum de cycles d'orchestration |

## Structure du projet

```
alvea/
├── agents/              # Les cinq agents (base_agent + jef, derick, zed, earl, chris)
├── core/                # Bus d'événements, client LLM, gestionnaire de tâches, moteur de planification
├── web/                 # Interface web locale
│   ├── server.py        # Serveur HTTP (routes API + fichiers statiques)
│   ├── runner.py        # Logique d'orchestration + état partagé (AppState)
│   └── static/          # index.html, style.css, app.js
├── plan/                # État d'exécution (plan.json)
├── tasks/               # Backlog de tâches (tasks.json)
├── runtime/             # État global et journal d'événements (events.log)
├── vision/              # Contraintes du projet (vision.json)
├── workspace/           # Code généré par les agents
└── main.py              # Point d'entrée — lance le serveur web
```

---

## Fichiers d'état

Alvea persiste l'intégralité de son état en JSON. Les trois fichiers principaux (`vision.json`, `tasks.json`, `plan.json`) forment le contrat de pilotage du système : la vision définit les règles, les tâches définissent le travail, le plan orchestre l'exécution.

### `vision/vision.json` — Contrat du projet

La vision est le document de référence partagé par tous les agents. Elle est écrite avant le lancement et peut être mise à jour entre les cycles. Elle définit **ce que le projet doit être** et **dans quelles conditions il est acceptable**.

```json
{
  "project_name": "Axoloop Alvea",
  "goal": {
    "primary_objective": "Description de l'objectif principal",
    "secondary_objectives": []
  },
  "architecture": {
    "style": "Hexagonal",
    "layers": ["domain", "application", "infrastructure"],
    "modules": ["PostgreSQL"]
  },
  "agents_contract": {
    "Jef":   { "role": "planner",     "rules": [] },
    "Zed":   { "role": "coder",       "rules": [] },
    "Earl":  { "role": "reviewer",    "rules": [] },
    "Chris": { "role": "executor",    "rules": [] },
    "Derick":{ "role": "orchestrator","rules": [] }
  },
  "quality_constraints": {
    "tests_required": true,
    "max_function_length": 40,
    "max_file_complexity": 10,
    "require_linting": true
  },
  "forbidden_patterns": ["import *", "eval(", "exec("],
  "allowed_patterns": [],
  "execution_policy": {
    "max_parallel_tasks": 1,
    "retry_limit": 0,
    "admission_strategy": "score_based"
  },
  "dependency_rules": [
    { "from": "domain", "to": "infrastructure" }
  ]
}
```

**Champs clés :**

- `architecture.style` — style architectural imposé à Zed et Earl lors de la génération et la revue (Hexagonal, Clean Architecture, MVC…). Mis à jour depuis le formulaire web avant chaque lancement.
- `architecture.modules` — composants techniques activés (ex. `PostgreSQL`, `Redis`). Influence les choix d'implémentation de Zed.
- `quality_constraints` — seuils de qualité qu'Earl vérifie lors de la revue. Si `tests_required` est vrai et qu'aucun test n'est produit, la revue échoue.
- `forbidden_patterns` — liste de patterns de code interdits. Earl rejette tout fichier qui en contient un.
- `execution_policy.max_parallel_tasks` — nombre maximum de tâches simultanées dans le pipeline. Actuellement `1` : les tâches s'exécutent en série.
- `execution_policy.admission_strategy` — stratégie d'admission des tâches. `score_based` : seules les tâches dont le score dépasse `admission_threshold` entrent dans la file.
- `agents_contract` — décrit le rôle de chaque agent. Les `rules` peuvent contenir des contraintes supplémentaires transmises aux prompts LLM.
- `dependency_rules` — règles de dépendance entre couches architecturales. Utilisées par Earl pour valider que le code ne viole pas l'architecture cible.

---

### `tasks/tasks.json` — Backlog des tâches

Produit par Jef lors de la phase de planification. Contient l'ensemble des tâches atomiques à réaliser, dans leur état courant.

```json
{
  "project_id": "Axoloop Alvea",
  "generated_by": "Jef",
  "task_model": {
    "granularity": "atomic",
    "definition_of_done": "task produces verifiable output in workspace/ + passes tests if applicable"
  },
  "backlog": [
    {
      "id": "TASK-001",
      "title": "Initialiser la structure du projet",
      "description": "Créer l'arborescence de dossiers et les fichiers de configuration de base.",
      "layer": "infrastructure",
      "type": "setup",
      "priority_hint": 0.9,
      "complexity": 0.2,
      "vision_alignment": 0.95,
      "dependencies": [],
      "outputs": ["workspace/pyproject.toml", "workspace/src/__init__.py"],
      "status": "pending",
      "tags": ["init", "structure"]
    }
  ],
  "metadata": {
    "total_tasks": 1,
    "generated_at": "2025-01-01T12:00:00.000Z",
    "last_updated": "2025-01-01T12:00:00.000Z"
  }
}
```

**Champs d'une tâche :**

| Champ | Type | Description |
|-------|------|-------------|
| `id` | `string` | Identifiant unique au format `TASK-NNN`. Utilisé pour les dépendances et les handoffs entre agents. |
| `layer` | `string` | Couche architecturale cible : `core`, `api`, `ui`, `infrastructure`, `test`. Earl vérifie la cohérence avec `vision.json`. |
| `type` | `string` | Nature du travail : `setup`, `feature`, `fix`, `refactor`. Chris choisit la commande d'exécution en fonction de ce champ. |
| `priority_hint` | `float [0-1]` | Urgence relative de la tâche. Contribue à 40 % du score d'admission. |
| `complexity` | `float [0-1]` | Estimation de la difficulté. Contribue négativement au score (tâche plus simple = score plus élevé). |
| `vision_alignment` | `float [0-1]` | Degré d'alignement avec les objectifs de la vision. Contribue à 40 % du score. |
| `dependencies` | `string[]` | IDs des tâches qui doivent être `completed` avant que celle-ci soit admissible. Derick ne l'admet pas si une dépendance est encore `pending` ou `blocked`. |
| `outputs` | `string[]` | Chemins des fichiers que Zed doit produire (relatifs à `workspace/`). Chris vérifie leur existence avant d'exécuter les commandes. |
| `status` | `string` | Cycle de vie : `pending` → `completed` ou `blocked`. |

**Cycle de vie d'une tâche :**

```
pending
  └─ [Derick] score >= seuil et dépendances satisfaites
       └─ admitted → ready_queue (plan.json)
            └─ [Derick] dispatch
                 └─ in_progress / Zed → in_progress / Earl → in_progress / Chris
                      ├─ succès → completed
                      └─ échec  → blocked
```

---

### `plan/plan.json` — État d'exécution de Derick

Plan est le tableau de bord opérationnel de Derick. Il gère les files d'attente, les métriques de cycle et l'historique des décisions d'admission.

```json
{
  "project_id": "Axoloop Alvea",
  "state": {
    "status": "running",
    "cycle": 3
  },
  "execution": {
    "ready_queue": [
      {
        "task_id": "TASK-002",
        "assigned_to": "Zed",
        "priority_score": 0.82,
        "admitted_at": "2025-01-01T12:01:00.000Z",
        "reason": "score=0.82 | priority=0.9 | alignment=0.85 | complexity=0.3"
      }
    ],
    "in_progress": [
      {
        "task_id": "TASK-001",
        "assigned_to": "Earl",
        "attempt": 2,
        "started_at": "2025-01-01T12:00:30.000Z"
      }
    ],
    "blocked": [
      {
        "task_id": "TASK-003",
        "reason": "Review échouée : fonction trop longue (52 lignes).",
        "blocked_at": "2025-01-01T12:00:45.000Z"
      }
    ]
  },
  "scheduling": {
    "max_parallel_tasks": 1,
    "selection_policy": "highest_score_first",
    "admission_threshold": 0.65
  },
  "decisions": [
    {
      "cycle": 1,
      "action": "ADMIT",
      "task_id": "TASK-001",
      "score": 0.87,
      "reason": "score=0.87 | priority=0.9 | alignment=0.95 | complexity=0.2"
    }
  ],
  "metrics": {
    "completed_tasks": 1,
    "failed_tasks": 1,
    "avg_completion_time": 0
  }
}
```

**Champs clés :**

- `state.cycle` — compteur de cycle incrémenté par Derick à chaque appel à `run_cycle()`. Sert de référence temporelle dans le journal d'événements.
- `execution.ready_queue` — tâches admises et en attente de dispatch. Derick sélectionne celle avec le `priority_score` le plus élevé (`highest_score_first`).
- `execution.in_progress` — tâche(s) actuellement traitée(s) par un agent. Le champ `assigned_to` change au fil des handoffs (`Zed` → `Earl` → `Chris`) ; `attempt` s'incrémente à chaque passage.
- `execution.blocked` — tâches qui ont échoué (revue rejetée ou exécution en erreur). Elles ne sont plus rééligibles.
- `scheduling.admission_threshold` — seuil minimal de score pour qu'une tâche entre dans `ready_queue`. Par défaut `0.65`. Une tâche dont le score est inférieur reste `pending` sans être bloquée.
- `decisions` — historique des admissions avec le score et le motif détaillé. Permet de comprendre pourquoi une tâche a été priorisée avant une autre.
- `metrics` — compteurs de tâches terminées et échouées, mis à jour par `complete_task()` et `fail_task()`.

**Formule de scoring (Derick) :**

```
score = (priority_hint × 0.4) + (vision_alignment × 0.4) + ((1 - complexity) × 0.2)
```

Une tâche critique (`priority_hint=1.0`), parfaitement alignée (`vision_alignment=1.0`) et simple (`complexity=0.0`) obtient un score de `1.0`. Une tâche de faible priorité et complexe peut rester en attente pendant plusieurs cycles si d'autres tâches lui sont systématiquement préférées.

---

## Journal d'événements

`runtime/events.log` est un fichier JSONL (une ligne = un objet JSON) en écriture seule. Il enregistre chaque transition d'état du système.

```jsonl
{"timestamp":"2025-01-01T12:00:00.000Z","agent":"Jef","event_type":"TASK_ADMITTED","target":"TASK-001","cycle":0,"payload":{"title":"Initialiser la structure","priority_hint":0.9}}
{"timestamp":"2025-01-01T12:00:05.000Z","agent":"Derick","event_type":"CYCLE_START","target":"system","cycle":1,"payload":{"cycle":1}}
{"timestamp":"2025-01-01T12:00:10.000Z","agent":"Derick","event_type":"TASK_STARTED","target":"TASK-001","cycle":1,"payload":{"assigned_to":"Zed"}}
{"timestamp":"2025-01-01T12:00:30.000Z","agent":"Zed","event_type":"CODE_WRITTEN","target":"TASK-001","cycle":1,"payload":{"files":["workspace/src/__init__.py"]}}
{"timestamp":"2025-01-01T12:00:35.000Z","agent":"Earl","event_type":"REVIEW_PASSED","target":"TASK-001","cycle":1,"payload":{"feedback":"Code conforme à la vision."}}
{"timestamp":"2025-01-01T12:00:40.000Z","agent":"Chris","event_type":"EXECUTION_SUCCESS","target":"TASK-001","cycle":1,"payload":{}}\
```

Types d'événements : `CYCLE_START`, `CYCLE_END`, `TASK_ADMITTED`, `TASK_STARTED`, `TASK_COMPLETED`, `TASK_BLOCKED`, `CODE_WRITTEN`, `CODE_MODIFIED`, `REVIEW_PASSED`, `REVIEW_FAILED`, `EXECUTION_SUCCESS`, `EXECUTION_CRASH`, `SYSTEM_ERROR`.
