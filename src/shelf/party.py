"""Party mode: people with accounts on this server join someone's playing ("X's party"), add
songs to it and vote to skip.

The host's playing device plays the party (it's that person's Connect session; see connect.py).
Songs people add go after the song that's playing, behind the ones added before them, so nobody
jumps the queue. A song is skipped once more than half of the people at the party have voted: the
host always counts, and guests count while they've had the party open in the last minute.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PRESENT = 60  # seconds since a guest last had the party open, to count as there


def insert_at(queue: list[int], index: int, pending: list[int]) -> int:
    """Where songs added now go in a queue playing `index`: after it and after the songs added
    earlier (`pending`, in the order added) that follow it."""
    at = index + 1 if queue else 0
    ahead = list(pending)
    while at < len(queue) and ahead and queue[at] in ahead:
        ahead.remove(queue[at])
        at += 1
    return min(at, len(queue))


@dataclass
class Party:
    host: int
    started: float
    members: dict[int, float] = field(default_factory=dict)  # guest -> last seen
    pending: list[int] = field(default_factory=list)  # songs added, not played yet, in order
    votes: set[int] = field(default_factory=set)
    vote_track: int | None = None

    def join(self, user: int, now: float) -> None:
        if user != self.host:
            self.members[user] = now

    def seen(self, user: int, now: float) -> None:
        if user in self.members:
            self.members[user] = now

    def leave(self, user: int) -> None:
        self.members.pop(user, None)
        self.votes.discard(user)

    def present(self, now: float) -> set[int]:
        return {self.host} | {u for u, at in self.members.items() if now - at <= PRESENT}

    def needed(self, now: float) -> int:
        return len(self.present(now)) // 2 + 1

    def vote(self, user: int, track: int, now: float) -> bool:
        """A vote to skip `track`. True when that makes enough (and the counting starts again)."""
        if track != self.vote_track:
            self.vote_track, self.votes = track, set()
        self.votes.add(user)
        self.votes &= self.present(now)
        if len(self.votes) >= self.needed(now):
            self.votes = set()
            return True
        return False

    def prune(self, queue: list[int], index: int) -> None:
        """Forget added songs that have played (or were taken out of the queue)."""
        upcoming = queue[index + 1:]
        self.pending = [t for t in self.pending if t in upcoming]
