package app.shelf.data

/** What can go wrong talking to a Shelf server, each with what the screens say about it. */
sealed class ShelfError(message: String, cause: Throwable? = null) : Exception(message, cause) {
    /** No answer: the server's off, or this phone isn't on its network. */
    class Offline(cause: Throwable? = null) : ShelfError("Couldn’t reach the server", cause)
    /** The sign-in isn't valid any more (password changed, signed out elsewhere). */
    class SignedOut : ShelfError("Signed out")
    /** Something answered, but it isn't Shelf. */
    class NotShelf : ShelfError("Not a Shelf server")
    /** The server said no, with its reason (FastAPI's `detail`). */
    class Server(val code: Int, message: String) : ShelfError(message)
}
