/*
 * Hapa DAW Engine
 *
 * A Web Audio shared-clock multitrack engine for the stem workstation.
 * HTMLMediaElement players remain as visible preview/debug controls, but the
 * professional workstation transport runs decoded AudioBuffers through a single
 * AudioContext clock so stems start, seek, mute, solo, pan, loop, and analyze
 * from one sample-accurate timeline.
 */
(function () {
  'use strict';

  class HapaDawEngine {
    constructor(options = {}) {
      const AudioCtor = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtor) throw new Error('Web Audio API is unavailable in this browser.');
      this.ctx = options.audioContext || new AudioCtor({ latencyHint: 'interactive' });
      this.masterGain = this.ctx.createGain();
      this.masterGain.gain.value = options.masterVolume ?? 1;
      this.masterAnalyser = this.ctx.createAnalyser();
      this.masterAnalyser.fftSize = 2048;
      this.masterGain.connect(this.masterAnalyser);
      this.masterAnalyser.connect(this.ctx.destination);

      this.tracks = new Map();
      this.scheduledSources = new Set();
      this.transportStartedAt = 0;
      this.transportOffset = 0;
      this.isPlaying = false;
      this.loopRegion = null;
      this.scheduleLookahead = options.scheduleLookahead || 0.035;
      this.onLoop = options.onLoop || null;
    }

    get sampleRate() { return this.ctx.sampleRate; }

    async resume() {
      if (this.ctx.state === 'suspended') await this.ctx.resume();
    }

    async decodeUrl(url) {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Could not fetch audio: ${response.status}`);
      const bytes = await response.arrayBuffer();
      return this.ctx.decodeAudioData(bytes.slice(0));
    }

    async loadTrack(trackSpec) {
      if (!trackSpec?.id) throw new Error('Track id is required.');
      const existing = this.tracks.get(trackSpec.id);
      if (existing?.url === trackSpec.url && existing?.buffer) {
        Object.assign(existing, { title: trackSpec.title || existing.title, type: trackSpec.type || existing.type });
        return existing;
      }
      const buffer = trackSpec.buffer || await this.decodeUrl(trackSpec.url);
      const gainNode = this.ctx.createGain();
      const panNode = this.ctx.createStereoPanner ? this.ctx.createStereoPanner() : null;
      const analyser = this.ctx.createAnalyser();
      analyser.fftSize = 2048;
      gainNode.gain.value = trackSpec.volume ?? 1;
      if (panNode) {
        panNode.pan.value = trackSpec.pan ?? 0;
        gainNode.connect(panNode);
        panNode.connect(analyser);
      } else {
        gainNode.connect(analyser);
      }
      analyser.connect(this.masterGain);
      const track = {
        id: trackSpec.id,
        title: trackSpec.title || trackSpec.id,
        type: trackSpec.type || 'track',
        url: trackSpec.url,
        path: trackSpec.path,
        buffer,
        gainNode,
        panNode,
        analyser,
        muted: Boolean(trackSpec.muted),
        solo: Boolean(trackSpec.solo),
        volume: trackSpec.volume ?? 1,
        pan: trackSpec.pan ?? 0,
        source: null,
        analysis: null,
      };
      this.tracks.set(track.id, track);
      this.applyMixState();
      return track;
    }

    clearTracks() {
      this.stopScheduledSources();
      for (const track of this.tracks.values()) {
        try { track.gainNode.disconnect(); } catch (_) {}
        try { track.panNode?.disconnect(); } catch (_) {}
        try { track.analyser.disconnect(); } catch (_) {}
      }
      this.tracks.clear();
      this.transportOffset = 0;
      this.transportStartedAt = 0;
      this.isPlaying = false;
      this.loopRegion = null;
    }

    currentTime() {
      if (!this.isPlaying) return this.transportOffset;
      return this.transportOffset + Math.max(0, this.ctx.currentTime - this.transportStartedAt);
    }

    play(offset = this.currentTime()) {
      const bounded = Math.max(0, Number(offset || 0));
      this.stopScheduledSources();
      this.transportOffset = bounded;
      this.transportStartedAt = this.ctx.currentTime + this.scheduleLookahead;
      this.isPlaying = true;
      this.applyMixState();
      for (const track of this.tracks.values()) this.scheduleTrack(track, bounded, this.transportStartedAt);
    }

    pause() {
      this.transportOffset = this.currentTime();
      this.isPlaying = false;
      this.stopScheduledSources();
    }

    stop() {
      this.transportOffset = 0;
      this.isPlaying = false;
      this.stopScheduledSources();
    }

    seek(offset) {
      const next = Math.max(0, Number(offset || 0));
      const wasPlaying = this.isPlaying;
      this.transportOffset = next;
      this.stopScheduledSources();
      if (wasPlaying) this.play(next);
    }

    setLoopRegion(start, end) {
      const s = Math.max(0, Number(start || 0));
      const e = Math.max(s + 0.001, Number(end || s));
      this.loopRegion = { start: s, end: e, duration: e - s };
      if (this.isPlaying) this.seek(s);
    }

    clearLoopRegion() {
      this.loopRegion = null;
    }

    scheduleTrack(track, offset, when) {
      if (!track?.buffer) return;
      const source = this.ctx.createBufferSource(); // createBufferSource()
      source.buffer = track.buffer;
      source.connect(track.gainNode);
      const duration = track.buffer.duration;
      const startOffset = Math.min(Math.max(0, offset), Math.max(0, duration - 0.001));
      const loop = this.loopRegion && this.loopRegion.end > this.loopRegion.start;
      if (loop) {
        source.loop = true;
        source.loopStart = this.loopRegion.start;
        source.loopEnd = this.loopRegion.end;
      }
      source.onended = () => this.scheduledSources.delete(source);
      this.scheduledSources.add(source);
      track.source = source;
      source.start(when, loop ? Math.max(this.loopRegion.start, startOffset) : startOffset);
    }

    stopScheduledSources() {
      for (const source of [...this.scheduledSources]) {
        try { source.onended = null; source.stop(0); } catch (_) {}
        try { source.disconnect(); } catch (_) {}
      }
      this.scheduledSources.clear();
      for (const track of this.tracks.values()) track.source = null;
    }

    setTrackMute(id, muted) {
      const track = this.tracks.get(id);
      if (!track) return;
      track.muted = Boolean(muted);
      this.applyMixState();
    }

    setTrackSolo(id, solo = true) {
      const track = this.tracks.get(id);
      if (!track) return;
      if (solo) {
        for (const t of this.tracks.values()) t.solo = false;
      }
      track.solo = Boolean(solo);
      this.applyMixState();
    }

    clearSolo() {
      for (const track of this.tracks.values()) track.solo = false;
      this.applyMixState();
    }

    setTrackVolume(id, volume) {
      const track = this.tracks.get(id);
      if (!track) return;
      track.volume = Math.max(0, Number(volume ?? 1));
      this.applyMixState();
    }

    setTrackPan(id, pan) {
      const track = this.tracks.get(id);
      if (!track) return;
      track.pan = Math.max(-1, Math.min(1, Number(pan || 0)));
      if (track.panNode) track.panNode.pan.setTargetAtTime(track.pan, this.ctx.currentTime, 0.01);
    }

    applyMixState() {
      const anySolo = [...this.tracks.values()].some((track) => track.solo);
      for (const track of this.tracks.values()) {
        const audible = !track.muted && (!anySolo || track.solo);
        const gain = audible ? track.volume : 0;
        track.gainNode.gain.setTargetAtTime(gain, this.ctx.currentTime, 0.01);
        if (track.panNode) track.panNode.pan.setTargetAtTime(track.pan || 0, this.ctx.currentTime, 0.01);
      }
    }

    getTrackAnalysis(id) {
      const track = this.tracks.get(id);
      if (!track) return null;
      if (track.analysis) return track.analysis;
      const waveform = this.computeWaveformPeaks(track.buffer, 720);
      const spectrogram = this.computeSpectrogramFrames(track.buffer, 120, 72);
      const fft = spectrogram.reduce((acc, frame) => frame.map((v, i) => Math.max(v, acc[i] || 0)), []);
      track.analysis = { waveform, spectrogram, fft, duration: track.buffer.duration, sampleRate: track.buffer.sampleRate, real: true };
      return track.analysis;
    }

    computeWaveformPeaks(buffer, buckets = 720) {
      const channel = buffer.getChannelData(0);
      const step = Math.max(1, Math.floor(channel.length / buckets));
      const peaks = [];
      for (let i = 0; i < buckets; i++) {
        const start = i * step;
        const end = Math.min(channel.length, start + step);
        let min = 0, max = 0, rms = 0;
        for (let j = start; j < end; j++) {
          const sample = channel[j] || 0;
          min = Math.min(min, sample);
          max = Math.max(max, sample);
          rms += sample * sample;
        }
        peaks.push({ min, max, rms: Math.sqrt(rms / Math.max(1, end - start)) });
      }
      return peaks;
    }

    computeSpectrogramFrames(buffer, frameCount = 120, binCount = 72) {
      const channel = buffer.getChannelData(0);
      const fftSize = 2048;
      const hop = Math.max(1, Math.floor((channel.length - fftSize) / Math.max(1, frameCount - 1)));
      const frames = [];
      for (let frame = 0; frame < frameCount; frame++) {
        const offset = frame * hop;
        const windowed = new Array(fftSize);
        for (let n = 0; n < fftSize; n++) {
          const hann = 0.5 * (1 - Math.cos((2 * Math.PI * n) / (fftSize - 1)));
          windowed[n] = (channel[offset + n] || 0) * hann;
        }
        const mags = this.fftMagnitudes(windowed);
        const grouped = [];
        for (let bin = 0; bin < binCount; bin++) {
          const start = Math.floor((bin / binCount) * mags.length);
          const end = Math.max(start + 1, Math.floor(((bin + 1) / binCount) * mags.length));
          const avg = mags.slice(start, end).reduce((a, b) => a + b, 0) / (end - start);
          grouped.push(Math.min(1, Math.log10(1 + avg * 32)));
        }
        frames.push(grouped);
      }
      return frames;
    }

    fftMagnitudes(samples) {
      const n = samples.length;
      const re = samples.slice();
      const im = new Array(n).fill(0);
      for (let i = 1, j = 0; i < n; i++) {
        let bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
      }
      for (let len = 2; len <= n; len <<= 1) {
        const ang = -2 * Math.PI / len;
        const wLenRe = Math.cos(ang), wLenIm = Math.sin(ang);
        for (let i = 0; i < n; i += len) {
          let wRe = 1, wIm = 0;
          for (let j = 0; j < len / 2; j++) {
            const uRe = re[i + j], uIm = im[i + j];
            const vRe = re[i + j + len / 2] * wRe - im[i + j + len / 2] * wIm;
            const vIm = re[i + j + len / 2] * wIm + im[i + j + len / 2] * wRe;
            re[i + j] = uRe + vRe; im[i + j] = uIm + vIm;
            re[i + j + len / 2] = uRe - vRe; im[i + j + len / 2] = uIm - vIm;
            const nextRe = wRe * wLenRe - wIm * wLenIm;
            wIm = wRe * wLenIm + wIm * wLenRe;
            wRe = nextRe;
          }
        }
      }
      return re.slice(0, n / 2).map((x, i) => Math.sqrt(x * x + im[i] * im[i]) / (n / 2));
    }
  }

  window.HapaDawEngine = HapaDawEngine;
})();
