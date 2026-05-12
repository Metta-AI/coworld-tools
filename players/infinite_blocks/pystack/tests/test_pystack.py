import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pystack


class PystackLogicTests(unittest.TestCase):
    def test_infers_piece_shape_and_origin(self):
        cells = [pystack.Cell(11, 20), pystack.Cell(10, 21), pystack.Cell(11, 21), pystack.Cell(12, 21)]

        active = pystack.infer_piece_from_cells(cells)

        self.assertTrue(active.found)
        self.assertEqual(active.kind, pystack.PieceKind.T)
        self.assertEqual(active.rotation, 0)
        self.assertEqual((active.origin_x, active.origin_y), (10, 20))

    def test_input_packet_protocols(self):
        mask = pystack.BUTTON_DOWN | pystack.BUTTON_SELECT

        self.assertEqual(pystack.input_packet(mask, "framebuffer"), bytes([0, mask]))
        self.assertEqual(pystack.input_packet(mask, "sprite"), bytes([0x84, mask]))

    def test_player_url_normalization(self):
        url = pystack.normalize_player_url("ws://localhost:2000", "agent 1", 3, "tok")

        self.assertEqual(url, "ws://localhost:2000/player?name=agent%201&slot=3&token=tok")
        self.assertEqual(pystack.derive_global_url(url), "ws://localhost:2000/global")

    def test_choose_placement_prefers_row_completion(self):
        width = 20
        height = 24
        lane_start = 6
        bottom_row = 20
        occupied = [False] * (width * height)
        for x in range(width):
            occupied[(bottom_row + 1) * width + x] = True
        for x in range(lane_start, lane_start + pystack.LINE_CLEAR_LENGTH):
            if x != lane_start + 3:
                occupied[bottom_row * width + x] = True
        active = pystack.ActivePiece(
            found=True,
            kind=pystack.PieceKind.I,
            rotation=1,
            origin_x=10,
            origin_y=0,
            cells=[pystack.Cell(12, y) for y in range(4)],
        )

        placement, target_row = pystack.choose_placement(occupied, width, height, lane_start, bottom_row, active)

        self.assertTrue(placement.found)
        self.assertLessEqual(target_row, bottom_row)
        self.assertIn(
            pystack.Cell(lane_start + 3, bottom_row),
            pystack.placed_cells(placement.x, placement.y, active.kind, placement.rotation),
        )
        self.assertGreaterEqual(placement.score, pystack.ROW_COMPLETION_BONUS)

    def test_frame_pystack_ignores_preview_cells(self):
        unpacked = [0] * (pystack.SCREEN_WIDTH * pystack.SCREEN_HEIGHT)

        def fill_cell(cx, cy, color):
            for py in range(pystack.CELL_PIXELS):
                for px in range(pystack.CELL_PIXELS):
                    sx = cx * pystack.CELL_PIXELS + px
                    sy = cy * pystack.CELL_PIXELS + py
                    unpacked[sy * pystack.SCREEN_WIDTH + sx] = color

        for cell in pystack.piece_cells(pystack.PieceKind.O, 0):
            fill_cell(59 + cell.x, cell.y, 4)
        for cell in pystack.piece_cells(pystack.PieceKind.T, 0):
            fill_cell(30 + cell.x, 16 + cell.y, 4)
        for x in range(pystack.FRAME_GRID_WIDTH):
            fill_cell(x, 48, pystack.TERRAIN_COLOR_INDEX)

        bot = pystack.FramePystack()
        grid = bot.grid_from_frame(pystack.pack_4bpp(unpacked))
        active = bot.active_piece(grid)

        self.assertTrue(active.found)
        self.assertEqual(active.kind, pystack.PieceKind.T)
        self.assertEqual((active.origin_x, active.origin_y), (30, 16))


if __name__ == "__main__":
    unittest.main()
