/*
 * Mikrofon sesini 16 kHz mono Int16 PCM'e çeviren AudioWorklet.
 * AudioContext hangi örnekleme hızında çalışırsa çalışsın (44.1/48 kHz)
 * burada 16 kHz'e indirilir; parçalar `chunkMs` uzunluğunda ana iş parçacığına gönderilir.
 */
class PcmDownsampler extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this.targetRate = opts.targetRate || 16000;
    this.ratio = sampleRate / this.targetRate; // sampleRate: AudioWorkletGlobalScope
    this.chunkSize = Math.round((this.targetRate * (opts.chunkMs || 320)) / 1000);
    this.out = new Int16Array(this.chunkSize);
    this.outIdx = 0;
    this.pos = 0; // giriş akışındaki kesirli okuma konumu
    this.carry = new Float32Array(0); // önceki bloktan kalan örnekler
    this.levelAcc = 0;
    this.levelN = 0;
    this.running = true;
    this.port.onmessage = (e) => {
      if (e.data === "stop") this.running = false;
    };
  }

  process(inputs) {
    if (!this.running) return false;
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) return true;

    // Çok kanallıysa monoya indir
    const n = input[0].length;
    let mono = input[0];
    if (input.length > 1) {
      mono = new Float32Array(n);
      for (let c = 0; c < input.length; c++) {
        const ch = input[c];
        for (let i = 0; i < n; i++) mono[i] += ch[i] / input.length;
      }
    }

    const buf = new Float32Array(this.carry.length + n);
    buf.set(this.carry, 0);
    buf.set(mono, this.carry.length);

    const ratio = this.ratio;
    const half = Math.max(1, Math.floor(ratio / 2));
    // Basit kutu filtresi (örtüşme önleyici) + doğrusal ara değerleme
    while (this.pos + half + 1 < buf.length) {
      const center = this.pos;
      const i0 = Math.floor(center);
      let sum = 0;
      let count = 0;
      if (ratio > 1.01) {
        for (let k = i0 - half + 1; k <= i0 + half; k++) {
          if (k >= 0 && k < buf.length) {
            sum += buf[k];
            count++;
          }
        }
      } else {
        const frac = center - i0;
        sum = buf[i0] * (1 - frac) + buf[i0 + 1] * frac;
        count = 1;
      }
      let s = sum / count;
      if (s > 1) s = 1;
      else if (s < -1) s = -1;
      this.levelAcc += s * s;
      this.levelN++;
      this.out[this.outIdx++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.outIdx === this.chunkSize) {
        const rms = Math.sqrt(this.levelAcc / Math.max(1, this.levelN));
        this.port.postMessage({ pcm: this.out.buffer, level: rms }, [this.out.buffer]);
        this.out = new Int16Array(this.chunkSize);
        this.outIdx = 0;
        this.levelAcc = 0;
        this.levelN = 0;
      }
      this.pos += ratio;
    }

    const consumed = Math.max(0, Math.floor(this.pos) - half);
    this.carry = buf.slice(consumed);
    this.pos -= consumed;
    return true;
  }
}

registerProcessor("pcm-downsampler", PcmDownsampler);
