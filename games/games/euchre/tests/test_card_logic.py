"""Tests for Euchre card logic (power computation, dealing)."""

import random

import pytest

from cogame_euchre.game import (
    CARD_RESOURCES,
    CARDS_PER_HAND,
    NUM_PLAYERS,
    SAME_COLOR,
    SUITS,
    compute_card_power,
)


class TestCardPower:
    """Test card power computation for all trump suits."""

    @pytest.mark.parametrize("trump", SUITS)
    def test_right_bower_is_highest(self, trump: str):
        right_bower = f"card_j{trump}"
        power = compute_card_power(right_bower, trump)
        assert power == 106

    @pytest.mark.parametrize("trump", SUITS)
    def test_left_bower_is_second_highest(self, trump: str):
        left_bower = f"card_j{SAME_COLOR[trump]}"
        power = compute_card_power(left_bower, trump)
        assert power == 105

    @pytest.mark.parametrize("trump", SUITS)
    def test_trump_ace_beats_non_trump(self, trump: str):
        trump_ace = compute_card_power(f"card_a{trump}", trump)
        # Non-trump ace of a different suit (not same color to avoid left bower)
        other_suits = [s for s in SUITS if s != trump and s != SAME_COLOR[trump]]
        for other in other_suits:
            non_trump_ace = compute_card_power(f"card_a{other}", trump)
            assert trump_ace > non_trump_ace

    @pytest.mark.parametrize("trump", SUITS)
    def test_trump_nine_beats_non_trump_ace(self, trump: str):
        trump_nine = compute_card_power(f"card_9{trump}", trump)
        other_suits = [s for s in SUITS if s != trump and s != SAME_COLOR[trump]]
        for other in other_suits:
            non_trump_ace = compute_card_power(f"card_a{other}", trump)
            assert trump_nine > non_trump_ace

    @pytest.mark.parametrize("trump", SUITS)
    def test_trump_rank_order(self, trump: str):
        """Right bower > Left bower > A > K > Q > 10 > 9 of trump."""
        right = compute_card_power(f"card_j{trump}", trump)
        left = compute_card_power(f"card_j{SAME_COLOR[trump]}", trump)
        ace = compute_card_power(f"card_a{trump}", trump)
        king = compute_card_power(f"card_k{trump}", trump)
        queen = compute_card_power(f"card_q{trump}", trump)
        ten = compute_card_power(f"card_10{trump}", trump)
        nine = compute_card_power(f"card_9{trump}", trump)
        assert right > left > ace > king > queen > ten > nine

    def test_non_trump_rank_order(self):
        """A > K > Q > J > 10 > 9 for non-trump, non-bower cards."""
        trump = "h"
        # Use clubs (not same color as hearts)
        powers = [compute_card_power(f"card_{r}c", trump) for r in ("a", "k", "q", "j", "10", "9")]
        assert powers == sorted(powers, reverse=True)
        assert all(p < 100 for p in powers)  # All below trump range

    def test_trump_cards_have_unique_powers(self):
        """All trump-suit cards (including bowers) should have distinct powers."""
        for trump in SUITS:
            trump_cards = [cr for cr in CARD_RESOURCES if cr.endswith(trump) or cr.endswith(SAME_COLOR[trump])]
            powers = [compute_card_power(cr, trump) for cr in trump_cards]
            # The 6 trump-suit cards + left bower = 7 unique powers in the 100-106 range
            trump_powers = [p for p in powers if p >= 100]
            assert len(set(trump_powers)) == 7  # 9,10,Q,K,A of trump + right bower + left bower


class TestDeckSetup:
    def test_deck_has_24_cards(self):
        assert len(CARD_RESOURCES) == 24

    def test_card_resource_names_valid(self):
        for cr in CARD_RESOURCES:
            assert cr.startswith("card_")
            name = cr[len("card_") :]
            suit = name[-1]
            rank = name[:-1]
            assert suit in SUITS
            assert rank in ("9", "10", "j", "q", "k", "a")

    def test_deal_distributes_all_cards(self):
        """Each player gets exactly 5 cards from the 24-card deck."""
        rng = random.Random(42)
        deck = list(CARD_RESOURCES)
        rng.shuffle(deck)
        hands = [deck[i * CARDS_PER_HAND : (i + 1) * CARDS_PER_HAND] for i in range(NUM_PLAYERS)]

        # 20 cards dealt, 4 in kitty
        all_dealt = [c for h in hands for c in h]
        assert len(all_dealt) == NUM_PLAYERS * CARDS_PER_HAND
        assert len(set(all_dealt)) == NUM_PLAYERS * CARDS_PER_HAND  # no duplicates
        for hand in hands:
            assert len(hand) == CARDS_PER_HAND
