# cogsguard

CogsGuard game runtime for Coworld.

Cogs vs Clips is a team-based territory control game. Cog agents capture and hold junctions while Clips — automated opponents — continuously expand by seizing adjacent territory.

## Install

```bash
pip install cogsguard
```

## Usage

```python
import cogsguard.game.game  # registers the "cogsguard" game
from cogsguard.core import get_game

game = get_game("cogsguard")
```

## Development

```bash
pip install -e '.[test]'
pytest
```
