# cogame-cogsguard

CogsGuard game package for [CoGames](https://github.com/Metta-AI/cogames).

Cogs vs Clips is a team-based territory control game. Cog agents capture and hold junctions while Clips — automated opponents — continuously expand by seizing adjacent territory.

## Install

```bash
pip install cogsguard
# or, via cogames extras:
pip install 'cogames[cogsguard]'
```

## Usage

```python
import cogsguard.game.game  # registers the "cogsguard" game
from cogames.game import get_game

game = get_game("cogsguard")
```

## Development

```bash
pip install -e '.[test]'
pytest
```
