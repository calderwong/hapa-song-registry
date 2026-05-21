import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'src' / 'index.html').read_text(encoding='utf-8')
RENDERER = (ROOT / 'src' / 'renderer.js').read_text(encoding='utf-8')


class UIFilterControlsTest(unittest.TestCase):
    def test_audio_and_variation_filter_controls_exist(self):
        self.assertIn('id="audioFilter"', INDEX)
        self.assertIn('value="no_music"', INDEX)
        self.assertIn('value="no_stems"', INDEX)
        self.assertIn('id="variationMin"', INDEX)
        self.assertIn('id="variationMax"', INDEX)

    def test_renderer_applies_audio_and_variation_filters_and_sorts(self):
        self.assertIn("'audioFilter'", RENDERER)
        self.assertIn('variationCountFor', RENDERER)
        self.assertIn('hasMusic', RENDERER)
        self.assertIn('variations_desc', RENDERER)
        self.assertIn('variations_asc', RENDERER)
        self.assertIn("audioMode === 'no_music'", RENDERER)
        self.assertIn("audioMode === 'no_stems'", RENDERER)

    def test_variation_specific_stem_ui_and_playback_guards_exist(self):
        self.assertIn('data-variation-stems', RENDERER)
        self.assertIn('stemsForVariation', RENDERER)
        self.assertIn('allStemsForMaster', RENDERER)
        self.assertIn('stemPlayable', RENDERER)
        self.assertIn('playStemAudio', RENDERER)
        self.assertIn('ensureStemAudio', RENDERER)
        self.assertIn('stem.playback.failed', RENDERER)

    def test_timeline_view_controls_exist(self):
        self.assertIn('data-tab="timeline"', INDEX)
        self.assertIn('id="tab-timeline"', INDEX)
        self.assertIn('renderTimeline', RENDERER)
        self.assertIn('timeline-bar', RENDERER)
        self.assertIn('data-timeline-clip', RENDERER)
        self.assertIn('8-count', RENDERER)
        self.assertIn('4-count', RENDERER)

    def test_timeline_can_be_promoted_to_full_page(self):
        self.assertIn('id="timelinePage"', INDEX)
        self.assertIn('data-open-timeline-page', RENDERER)
        self.assertIn('openTimelinePage', RENDERER)
        self.assertIn('closeTimelinePage', RENDERER)
        self.assertIn('timeline-page active', RENDERER)

    def test_stems_have_detached_native_players(self):
        self.assertIn('data-stem-native', RENDERER)
        self.assertIn('hydrateNativeStemPlayers', RENDERER)
        self.assertIn('detachedStemPlayer', RENDERER)
        self.assertIn('pauseAllStemsExcept', RENDERER)
        self.assertIn('seekStemSession', RENDERER)

    def test_complete_stem_workstation_page_exists(self):
        self.assertIn('id="stemLabPage"', INDEX)
        self.assertIn('data-open-stem-lab', RENDERER)
        self.assertIn('openStemLabPage', RENDERER)
        self.assertIn('renderStemLabPage', RENDERER)
        self.assertIn('stem-lab-page active', RENDERER)

    def test_stem_workstation_has_master_timeline_and_visuals(self):
        self.assertIn('masterTimeline', RENDERER)
        self.assertIn('stemLabMasterTimeline', RENDERER)
        self.assertIn('data-stem-mute', RENDERER)
        self.assertIn('checked', RENDERER)
        self.assertIn('stemWaveformCanvas', RENDERER)
        self.assertIn('stemSpectrogramCanvas', RENDERER)
        self.assertIn('stemFftCanvas', RENDERER)
        self.assertIn('drawStemAnalysisVisuals', RENDERER)

    def test_loop_pointer_marker_capture_feedback_exists(self):
        self.assertIn('dropLoopPointer', RENDERER)
        self.assertIn('capturePointerLoop', RENDERER)
        self.assertIn('endLoopMarker', RENDERER)
        self.assertIn('loopCaptureFlash', RENDERER)
        self.assertIn('data-loop-counts="4"', RENDERER)
        self.assertIn('data-loop-counts="8"', RENDERER)
        self.assertIn('data-end-loop-marker', RENDERER)
        self.assertIn('data-dock-to-mixer', RENDERER)

    def test_workstation_uses_real_audio_analysis_pipeline(self):
        self.assertIn('decodeAudioData', RENDERER)
        self.assertIn('computeWaveformPeaks', RENDERER)
        self.assertIn('computeSpectrogramFrames', RENDERER)
        self.assertIn('renderAnalysisCanvas', RENDERER)
        self.assertIn('state.stemAnalysis', RENDERER)
        self.assertNotIn('seed = [...`${id}:${kind}:${idx}`]', RENDERER)

    def test_workstation_has_synchronized_multistem_transport(self):
        self.assertIn('playStemSession', RENDERER)
        self.assertIn('seekStemSession', RENDERER)
        self.assertIn('state.stemMuteState', RENDERER)
        self.assertIn('state.stemSoloState', RENDERER)
        self.assertIn('applyStemMixState', RENDERER)
        self.assertNotIn('pauseAllStemsExcept(stem.id);', RENDERER)

    def test_workstation_loop_capture_is_count_based_and_renderable(self):
        self.assertIn('countsToSeconds', RENDERER)
        self.assertIn('capturePointerLoopCounts', RENDERER)
        self.assertIn('data-loop-counts="4"', RENDERER)
        self.assertIn('data-loop-counts="8"', RENDERER)
        self.assertIn('createClip({ ...payload, inputPath: src.path })', RENDERER)
        self.assertIn("renderStatus: 'metadata-only'", RENDERER)

    def test_loop_playback_and_mixer_respect_loop_regions(self):
        self.assertIn('playStemLoopRegion', RENDERER)
        self.assertIn('buildMixerInputs', RENDERER)
        self.assertIn('start: loop.start', RENDERER)
        self.assertIn('end: loop.end', RENDERER)
        self.assertIn('atrim', (ROOT / 'src' / 'main.js').read_text(encoding='utf-8'))
        self.assertIn('asetpts=PTS-STARTPTS', (ROOT / 'src' / 'main.js').read_text(encoding='utf-8'))

    def test_professional_daw_engine_is_loaded_before_renderer(self):
        self.assertIn('<script src="daw-engine.js"></script>', INDEX)
        self.assertLess(INDEX.index('daw-engine.js'), INDEX.index('renderer.js'))

    def test_daw_engine_has_shared_clock_buffer_tracks_and_buses(self):
        engine_path = ROOT / 'src' / 'daw-engine.js'
        self.assertTrue(engine_path.exists(), 'src/daw-engine.js should define the Web Audio DAW engine')
        engine = engine_path.read_text(encoding='utf-8')
        for token in [
            'class HapaDawEngine',
            'createBufferSource()',
            'this.transportStartedAt',
            'this.transportOffset',
            'scheduleLookahead',
            'masterGain',
            'track.gainNode',
            'track.panNode',
            'track.analyser',
            'setLoopRegion',
            'scheduledSources',
            'sampleRate',
            'decodeAudioData',
        ]:
            self.assertIn(token, engine)

    def test_renderer_uses_daw_engine_for_stem_session_and_loop_playback(self):
        for token in [
            'state.dawEngine',
            'ensureDawEngine',
            'loadDawSessionForCurrent',
            'state.dawEngine.play',
            'state.dawEngine.pause',
            'state.dawEngine.seek',
            'state.dawEngine.setTrackMute',
            'state.dawEngine.setTrackSolo',
            'state.dawEngine.setLoopRegion',
            'state.dawEngine.clearLoopRegion',
            'state.dawEngine.getTrackAnalysis',
        ]:
            self.assertIn(token, RENDERER)

    def test_daw_utility_is_visible_in_workstation_ui(self):
        for token in [
            'dawUtilityPanel',
            'DAW Engine Online',
            'Shared AudioContext clock',
            'Decoded AudioBuffer tracks',
            'Sample-accurate loop region',
            'data-daw-play',
            'data-daw-pause',
            'data-daw-clear-loop',
            'id="dawStatusReadout"',
            'renderDawUtilityPanel',
            'updateDawStatusReadout',
            'wireDawUtilityControls',
        ]:
            self.assertIn(token, RENDERER)

    def test_daw_utility_has_styles(self):
        styles = (ROOT / 'src' / 'styles.css').read_text(encoding='utf-8')
        for token in ['.daw-utility-panel', '.daw-metric-grid', '.daw-signal-pill', '.daw-transport-strip']:
            self.assertIn(token, styles)

    def test_workstation_visuals_are_live_wired_to_daw_audio(self):
        for token in [
            'drawLiveDawVisuals',
            'requestAnimationFrame(drawLiveDawVisuals)',
            'getByteTimeDomainData',
            'getByteFrequencyData',
            'drawPlayheadOverlay',
            'data-analysis-stem-id',
            'state.dawVisualRaf',
            'state.dawSpectrogramHistory',
        ]:
            self.assertIn(token, RENDERER)
    def test_prompt_group_and_mashup_filter_controls_exist(self):
        self.assertIn('id="promptGroupFilter"', INDEX)
        self.assertIn('id="contentTypeFilter"', INDEX)
        self.assertIn('value="mashup"', INDEX)
        self.assertIn('value="non_mashup"', INDEX)
        self.assertIn('prompt groups', INDEX.lower())

    def test_renderer_search_filters_and_badges_include_prompt_groups_and_mashups(self):
        for token in [
            "'promptGroupFilter'",
            "'contentTypeFilter'",
            'promptGroupsForMaster',
            'promptGroupForSong',
            'contentTypeFor',
            "contentMode === 'mashup'",
            "contentMode === 'non_mashup'",
            'promptGroupText',
            'isMashup',
            'mashup',
        ]:
            self.assertIn(token, RENDERER)


if __name__ == '__main__':
    unittest.main()
