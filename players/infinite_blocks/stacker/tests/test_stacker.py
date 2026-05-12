import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stacker


class StackerLogicTests(unittest.TestCase):
    def test_infers_piece_shape_and_origin(self):
        cells = [stacker.Cell(11, 20), stacker.Cell(10, 21), stacker.Cell(11, 21), stacker.Cell(12, 21)]

        active = stacker.infer_piece_from_cells(cells)

        self.assertTrue(active.found)
        self.assertEqual(active.kind, stacker.PieceKind.T)
        self.assertEqual(active.rotation, 0)
        self.assertEqual((active.origin_x, active.origin_y), (10, 20))

    def test_input_packet_protocols(self):
        mask = stacker.BUTTON_DOWN | stacker.BUTTON_SELECT

        self.assertEqual(stacker.input_packet(mask, "framebuffer"), bytes([0, mask]))
        self.assertEqual(stacker.input_packet(mask, "sprite"), bytes([0x84, mask]))

    def test_player_url_normalization(self):
        url = stacker.normalize_player_url("ws://localhost:2000", "agent 1", 3, "tok")

        self.assertEqual(url, "ws://localhost:2000/player?name=agent%201&slot=3&token=tok")
        self.assertEqual(stacker.derive_global_url(url), "ws://localhost:2000/global")

    def test_choose_placement_prefers_row_completion(self):
        width = 20
        height = 24
        lane_start = 6
        bottom_row = 20
        occupied = [False] * (width * height)
        for x in range(width):
            occupied[(bottom_row + 1) * width + x] = True
        for x in range(lane_start, lane_start + stacker.LINE_CLEAR_LENGTH):
            if x != lane_start + 3:
                occupied[bottom_row * width + x] = True
        active = stacker.ActivePiece(
            found=True,
            kind=stacker.PieceKind.I,
            rotation=1,
            origin_x=10,
            origin_y=0,
            cells=[stacker.Cell(12, y) for y in range(4)],
        )

        placement, target_row = stacker.choose_placement(occupied, width, height, lane_start, bottom_row, active)

        self.assertTrue(placement.found)
        self.assertLessEqual(target_row, bottom_row)
        self.assertIn(
            stacker.Cell(lane_start + 3, bottom_row),
            stacker.placed_cells(placement.x, placement.y, active.kind, placement.rotation),
        )
        self.assertGreaterEqual(placement.score, stacker.ROW_COMPLETION_BONUS)

    def test_frame_stacker_ignores_preview_cells(self):
        unpacked = [0] * (stacker.SCREEN_WIDTH * stacker.SCREEN_HEIGHT)

        def fill_cell(cx, cy, color):
            for py in range(stacker.CELL_PIXELS):
                for px in range(stacker.CELL_PIXELS):
                    sx = cx * stacker.CELL_PIXELS + px
                    sy = cy * stacker.CELL_PIXELS + py
                    unpacked[sy * stacker.SCREEN_WIDTH + sx] = color

        for cell in stacker.piece_cells(stacker.PieceKind.O, 0):
            fill_cell(59 + cell.x, cell.y, 4)
        for cell in stacker.piece_cells(stacker.PieceKind.T, 0):
            fill_cell(30 + cell.x, 16 + cell.y, 4)
        for x in range(stacker.FRAME_GRID_WIDTH):
            fill_cell(x, 48, stacker.TERRAIN_COLOR_INDEX)

        bot = stacker.FrameStacker()
        grid = bot.grid_from_frame(stacker.pack_4bpp(unpacked))
        active = bot.active_piece(grid)

        self.assertTrue(active.found)
        self.assertEqual(active.kind, stacker.PieceKind.T)
        self.assertEqual((active.origin_x, active.origin_y), (30, 16))


if __name__ == "__main__":
    unittest.main()
