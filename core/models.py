"""models.py: struktur data inti AutoClip.

File ini hanya berisi "wadah" data. Tidak ada database, tidak ada AI.
Semua modul lain (kalimat, skoring, seleksi clip) memakai wadah ini.
"""
from dataclasses import dataclass, field

# Tanda baca yang menandakan sebuah kalimat selesai
TANDA_AKHIR = (".", "?", "!", "…")


@dataclass(frozen=True)
class Word:
    """Satu kata hasil transkripsi, lengkap dengan waktunya (dalam detik)."""
    text: str
    start: float
    end: float


@dataclass
class Sentence:
    """Satu kalimat = daftar kata berurutan."""
    words: list[Word]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Candidate:
    """Calon clip = gabungan beberapa kalimat berurutan."""
    sentences: list[Sentence]

    @property
    def start(self) -> float:
        return self.sentences[0].start

    @property
    def end(self) -> float:
        return self.sentences[-1].end

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def words(self) -> list[Word]:
        return [w for s in self.sentences for w in s.words]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)


@dataclass
class ScoredCandidate:
    """Calon clip yang sudah dinilai. hook/flow/value/trend bernilai 0-1, score 0-100."""
    candidate: Candidate
    hook: float
    flow: float
    value: float
    trend: float
    score: float

    @property
    def start(self) -> float:
        return self.candidate.start

    @property
    def end(self) -> float:
        return self.candidate.end


@dataclass
class EnergyProfile:
    """Kekerasan suara (energi audio) yang diukur tiap `step` detik."""
    step: float
    values: list[float] = field(default_factory=list)

    def mean(self, start: float, end: float) -> float:
        """Rata-rata energi pada rentang waktu start..end."""
        if not self.values:
            return 0.0
        awal = max(0, int(start / self.step))
        akhir = min(len(self.values), max(awal + 1, int(end / self.step) + 1))
        potongan = self.values[awal:akhir]
        return sum(potongan) / len(potongan) if potongan else 0.0

    def overall_mean(self) -> float:
        """Rata-rata energi seluruh video."""
        return sum(self.values) / len(self.values) if self.values else 0.0
