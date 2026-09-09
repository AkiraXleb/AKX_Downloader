"""
Tests unitarios para akx/naming.py (lógica pura, sin I/O).

Correr con:
    py -3.10 -m unittest tests.test_naming -v
o simplemente:
    py -3.10 -m unittest discover
"""
import unittest

from akx.naming import (
    build_name_from_metadata,
    clean_filename,
    clean_title,
    reorder_to_artist_first,
    sanitize_filename_part,
)


class CleanTitleTests(unittest.TestCase):

    def test_noop_on_empty(self):
        self.assertEqual(clean_title(""), "")

    def test_noop_on_plain_title(self):
        self.assertEqual(clean_title("Bohemian Rhapsody"), "Bohemian Rhapsody")

    def test_strips_youtube_id_brackets(self):
        self.assertEqual(clean_title("Never Gonna Give You Up [dQw4w9WgXcQ]"),
                          "Never Gonna Give You Up")

    def test_strips_youtube_id_parens(self):
        self.assertEqual(clean_title("Some Song (dQw4w9WgXcQ)"), "Some Song")

    def test_strips_official_video_parens(self):
        self.assertEqual(clean_title("Song Title (Official Video)"), "Song Title")

    def test_strips_official_music_video(self):
        self.assertEqual(clean_title("Song Title (Official Music Video)"), "Song Title")

    def test_strips_video_oficial(self):
        self.assertEqual(clean_title("Cancion (Video Oficial)"), "Cancion")

    def test_strips_videoclip_oficial_no_space(self):
        self.assertEqual(clean_title("Cancion (VideoclipOficial)"), "Cancion")

    def test_strips_lyric_video(self):
        self.assertEqual(clean_title("Song (Lyric Video)"), "Song")

    def test_strips_con_letra(self):
        self.assertEqual(clean_title("Cancion (Con Letra)"), "Cancion")

    def test_strips_subtitulado(self):
        self.assertEqual(clean_title("Song (Subtitulado al Español)"), "Song")

    def test_strips_quality_marker_parens(self):
        self.assertEqual(clean_title("Song (HD)"), "Song")
        self.assertEqual(clean_title("Song (4K)"), "Song")

    def test_strips_trailing_pipe_noise(self):
        self.assertEqual(clean_title("Cancion | Video Oficial HD"), "Cancion")

    def test_strips_trailing_dash_noise(self):
        self.assertEqual(clean_title("Cancion - Official Video"), "Cancion")

    def test_strips_trailing_loose_pipe(self):
        self.assertEqual(clean_title("Cancion | VIDEO OFICIAL |"), "Cancion")

    def test_strips_trailing_emojis(self):
        self.assertEqual(clean_title("Cancion Nueva \U0001F525✨"), "Cancion Nueva")

    def test_strips_trailing_hashtags(self):
        self.assertEqual(clean_title("Cancion Nueva #musica #pop"), "Cancion Nueva")

    def test_strips_prod_by(self):
        self.assertEqual(clean_title("Song (prod. by DJKhaled)"), "Song")

    def test_strips_prod_por(self):
        self.assertEqual(clean_title("Cancion (Prod. por Beatmaker)"), "Cancion")

    def test_strips_remastered_with_year(self):
        self.assertEqual(clean_title("Song (Remastered 2011)"), "Song")

    def test_strips_slowed_reverb(self):
        self.assertEqual(clean_title("Song (Slowed + Reverb)"), "Song")

    def test_strips_sped_up(self):
        self.assertEqual(clean_title("Song (Sped Up)"), "Song")

    def test_keeps_live(self):
        self.assertEqual(clean_title("Song (Live)"), "Song (Live)")

    def test_keeps_acoustic(self):
        self.assertEqual(clean_title("Song (Acoustic)"), "Song (Acoustic)")

    def test_keeps_remix(self):
        self.assertEqual(clean_title("Song (Remix)"), "Song (Remix)")

    def test_keeps_explicit(self):
        self.assertEqual(clean_title("Song (Explicit)"), "Song (Explicit)")

    def test_keeps_feat(self):
        self.assertEqual(clean_title("Song (feat. Other Artist)"), "Song (feat. Other Artist)")

    def test_fullwidth_pipe_normalized_before_cleanup(self):
        self.assertEqual(clean_title("Cancion ｜ Video Oficial"), "Cancion")

    def test_fullwidth_chars_normalized(self):
        # No noise term involved here, just normalization + no crash.
        self.assertEqual(clean_title("Track＇s Name"), "Track's Name")

    def test_multiple_nested_noise_parens(self):
        self.assertEqual(clean_title("Song (Official Video) (HD)"), "Song")

    def test_does_not_collapse_to_empty_returns_original(self):
        # If cleaning would leave nothing, fall back to the original string.
        self.assertEqual(clean_title("(Official Video)"), "(Official Video)")

    def test_collapses_internal_whitespace(self):
        self.assertEqual(clean_title("Song    Title   (Official Video)"), "Song Title")

    def test_strips_leading_separators(self):
        self.assertEqual(clean_title("- Song Title"), "Song Title")


class CleanFilenameTests(unittest.TestCase):

    def test_preserves_extension(self):
        self.assertEqual(clean_filename("Song (Official Video).mp3"), "Song.mp3")

    def test_preserves_extension_mp4(self):
        self.assertEqual(clean_filename("Cancion [dQw4w9WgXcQ].mp4"), "Cancion.mp4")

    def test_noop_without_noise(self):
        self.assertEqual(clean_filename("Plain Name.mp3"), "Plain Name.mp3")


class SanitizeFilenamePartTests(unittest.TestCase):

    def test_empty_string(self):
        self.assertEqual(sanitize_filename_part(""), "")

    def test_none_like_falsy(self):
        self.assertEqual(sanitize_filename_part(None), "")

    def test_strips_forbidden_windows_chars(self):
        self.assertEqual(sanitize_filename_part('Artist: "Best"? <One>'), "Artist Best One")

    def test_collapses_whitespace(self):
        self.assertEqual(sanitize_filename_part("Artist    Name"), "Artist Name")

    def test_strips_trailing_dots_and_spaces(self):
        self.assertEqual(sanitize_filename_part("Artist Name. . "), "Artist Name")


class BuildNameFromMetadataTests(unittest.TestCase):

    def test_none_info_returns_none(self):
        self.assertIsNone(build_name_from_metadata(None))

    def test_empty_info_returns_none(self):
        self.assertIsNone(build_name_from_metadata({}))

    def test_artist_and_track_explicit(self):
        info = {"artist": "Rick Astley", "track": "Never Gonna Give You Up"}
        self.assertEqual(build_name_from_metadata(info),
                          "Rick Astley - Never Gonna Give You Up")

    def test_artist_and_title_gets_prefixed(self):
        info = {"artist": "Rick Astley", "title": "Never Gonna Give You Up (Official Video)"}
        self.assertEqual(build_name_from_metadata(info),
                          "Rick Astley - Never Gonna Give You Up")

    def test_title_already_prefixed_with_artist(self):
        info = {"artist": "Rick Astley",
                "title": "Rick Astley - Never Gonna Give You Up (Official Video)"}
        self.assertEqual(build_name_from_metadata(info),
                          "Rick Astley - Never Gonna Give You Up")

    def test_title_equals_artist_avoids_duplication(self):
        info = {"artist": "Rick Astley", "title": "Rick Astley"}
        self.assertEqual(build_name_from_metadata(info), "Rick Astley")

    def test_creator_used_as_artist_fallback(self):
        info = {"creator": "Some Composer", "title": "A Piece"}
        self.assertEqual(build_name_from_metadata(info), "Some Composer - A Piece")

    def test_only_title_falls_back_to_clean_title(self):
        info = {"title": "Song (Official Video)"}
        self.assertEqual(build_name_from_metadata(info), "Song")

    def test_no_usable_fields_returns_none(self):
        info = {"uploader": "SomeChannel"}
        self.assertIsNone(build_name_from_metadata(info))


class ReorderToArtistFirstTests(unittest.TestCase):

    def test_no_metadata_noop(self):
        self.assertEqual(reorder_to_artist_first("Song | Artist", None), ("Song | Artist", False))

    def test_empty_stem_noop(self):
        self.assertEqual(reorder_to_artist_first("", "Artist"), ("", False))

    def test_reorders_pipe_separated(self):
        stem, changed = reorder_to_artist_first("Never Gonna Give You Up | Rick Astley",
                                                  "Rick Astley")
        self.assertTrue(changed)
        self.assertEqual(stem, "Rick Astley - Never Gonna Give You Up")

    def test_reorders_dash_separated(self):
        stem, changed = reorder_to_artist_first("Never Gonna Give You Up - Rick Astley",
                                                  "Rick Astley")
        self.assertTrue(changed)
        self.assertEqual(stem, "Rick Astley - Never Gonna Give You Up")

    def test_already_artist_first_noop(self):
        stem, changed = reorder_to_artist_first("Rick Astley - Never Gonna Give You Up",
                                                  "Rick Astley")
        self.assertFalse(changed)
        self.assertEqual(stem, "Rick Astley - Never Gonna Give You Up")

    def test_channel_suffix_vevo_stripped_for_match(self):
        stem, changed = reorder_to_artist_first("Hello | AdeleVEVO", "AdeleVEVO")
        self.assertTrue(changed)
        self.assertEqual(stem, "AdeleVEVO - Hello")

    def test_channel_suffix_game_with_collaboration_connector_y(self):
        # Documented example from naming.py docstring:
        # "ZARCORT Y TOWN" matches artist "ZarcortGame" because "y" is a
        # Spanish collaboration connector after stripping the channel suffix.
        stem, changed = reorder_to_artist_first("Track Title | ZARCORT Y TOWN", "ZarcortGame")
        self.assertTrue(changed)
        self.assertEqual(stem, "ZARCORT Y TOWN - Track Title")

    def test_collaboration_connector_comma(self):
        stem, changed = reorder_to_artist_first("Track | Zarcort, Piter-G", "ZarcortGame")
        self.assertTrue(changed)
        self.assertEqual(stem, "Zarcort, Piter-G - Track")

    def test_collaboration_connector_feat(self):
        stem, changed = reorder_to_artist_first("Track | Cyclo ft. Kronno", "CycloMusic")
        self.assertTrue(changed)
        self.assertEqual(stem, "Cyclo ft. Kronno - Track")

    def test_two_separators_is_ambiguous_noop(self):
        stem, changed = reorder_to_artist_first("A | B | Rick Astley", "Rick Astley")
        self.assertFalse(changed)
        self.assertEqual(stem, "A | B | Rick Astley")

    def test_neither_side_matches_artist_noop(self):
        stem, changed = reorder_to_artist_first("Some Song | Some Channel", "Rick Astley")
        self.assertFalse(changed)
        self.assertEqual(stem, "Some Song | Some Channel")

    def test_missing_pipe_spacing_gets_normalized(self):
        stem, changed = reorder_to_artist_first("Track|Rick Astley", "Rick Astley")
        self.assertTrue(changed)
        self.assertEqual(stem, "Rick Astley - Track")

    def test_normalization_without_reorder_still_reports_change(self):
        # Left side already is the artist -> no reorder, but the loose pipe
        # spacing still gets normalized and reported as a change.
        stem, changed = reorder_to_artist_first("Rick Astley|Track", "Rick Astley")
        self.assertTrue(changed)
        self.assertEqual(stem, "Rick Astley | Track")


if __name__ == "__main__":
    unittest.main()
