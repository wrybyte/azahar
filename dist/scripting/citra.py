# Copyright Citra Emulator Project / Azahar Emulator Project
# Licensed under GPLv2 or any later version
# Refer to the license.txt file included.

"""
Provide Python scripting support for the Azahar Emulator.

Classes:
    Citra: Handle reading and writing memory in Azahar.
"""

__all__ = ["Citra"]

import enum
import errno
import random
import socket
import struct
import sys

# The minimum supported Python version for scripting.
MIN_PYTHON = (3, 10)

if sys.version_info < MIN_PYTHON:
    version = ".".join(str(i) for i in MIN_PYTHON)
    sys.exit(f"Python version {version} or later is required.")


# The default port used by Azahar.
CITRA_PORT = 45987

# Define protocol constants.
CURRENT_REQUEST_VERSION = 1
MAX_REQUEST_DATA_SIZE = 32
MAX_PACKET_SIZE = 48
TIMEOUT_SECONDS = 1

# Define packet structure using compiled struct objects.
HEADER_STRUCT = struct.Struct("4I")
DATA_STRUCT = struct.Struct("2I")


class RequestType(enum.IntEnum):
    """
    Indicate the RPC communication request type.

    Attributes:
        ReadMemory: Request type for reading memory from Azahar.
        WriteMemory: Request type for writing memory to Azahar.
    """

    ReadMemory = 1
    WriteMemory = 2


class Citra:
    """
    Handle reading and writing memory in Azahar.

    Communicates to the Azahar RPC server over UDP.

    Attributes:
        socket: UDP socket object used for communicating with Azahar.
        address: The IP address of the RPC server.
        port: The port number used to communicate with the Azahar RPC
            server.

    Methods:
        is_connected() -> bool:
            Check if the Azahar RPC server is running.
        read_memory(read_address, read_size): -> bytes | None:
            Read game data from a memory address in Azahar.
        write_memory(write_address, write_contents) -> bool:
            Write data to a memory address in Azahar.
    """

    def __init__(
        self, address: str = "127.0.0.1", port: int = CITRA_PORT
    ) -> None:
        """
        Initialise the RPC client.

        Args:
            address: The IP address of the RPC server. Defaults to
                localhost address "127.0.0.1".
            port: The port number used to communicate with the Azahar
                RPC server. Defaults to port 45987.
        """
        self.socket: socket.socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM
        )
        self.socket.settimeout(TIMEOUT_SECONDS)
        self.address: str = address
        self.port: int = port

    def is_connected(self) -> bool:
        """
        Check if the Azahar RPC server is running.

        Returns:
            True if it is possible to connect to Azahar, False otherwise.

        Examples:
            >>> c.is_connected()
            True
        """
        # Creating a new socket is neccessary due to the nature of binding.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # Attempt to bind to the address Azahar uses.
            try:
                sock.bind((self.address, self.port))
            except OSError as e:
                # Address already in use.
                if e.errno == errno.EADDRINUSE:
                    return True

                # Reraise if the exception was not `EADDRINUSE`.
                raise

        return False

    def _generate_header(
        self, request_type: RequestType, data_size: int
    ) -> tuple[bytes, int]:
        request_id = random.getrandbits(32)
        header = HEADER_STRUCT.pack(
            CURRENT_REQUEST_VERSION, request_id, request_type, data_size
        )
        return (header, request_id)

    def _read_and_validate_header(
        self, raw_reply: bytes, expected_id: int, expected_type: RequestType
    ) -> bytes | None:
        fields: tuple[int, int, int, int] = HEADER_STRUCT.unpack(
            raw_reply[: HEADER_STRUCT.size]
        )
        reply_version, reply_id, reply_type, reply_data_size = fields

        if (
            reply_version == CURRENT_REQUEST_VERSION
            and reply_id == expected_id
            and reply_type == expected_type
            and reply_data_size == len(raw_reply[HEADER_STRUCT.size :])
        ):
            return raw_reply[HEADER_STRUCT.size :]

        return None

    def read_memory(self, read_address: int, read_size: int) -> bytes | None:
        r"""
        Read game data from a memory address in Azahar.

        Args:
            read_address: The memory address to start reading from.
            read_size: The number of bytes to read from the `read_address`.

        Returns:
            The data read from memory, if successful. Returns `None` if the
            Azahar RPC server fails to respond or if no data is recieved.

        Examples:
            >>> c.read_memory(0x100000, 4)
            b'\x07\x00\x00\xeb'
        """
        result = b""

        while read_size > 0:
            temp_read_size = min(read_size, MAX_REQUEST_DATA_SIZE)
            request_data = DATA_STRUCT.pack(read_address, temp_read_size)
            request, request_id = self._generate_header(
                RequestType.ReadMemory, len(request_data)
            )
            request += request_data

            _ = self.socket.sendto(request, (self.address, self.port))

            try:
                raw_reply = self.socket.recv(MAX_PACKET_SIZE)
            except TimeoutError:
                return None

            reply_data = self._read_and_validate_header(
                raw_reply, request_id, RequestType.ReadMemory
            )

            if reply_data is None:
                return None

            result += reply_data
            read_size -= len(reply_data)
            read_address += len(reply_data)

        return result

    def write_memory(
        self,
        write_address: int,
        write_contents: bytes | bytearray | memoryview,
    ) -> bool:
        r"""
        Write data to a memory address in Azahar.

        Args:
            write_address: The memory address to write to.
            write_contents: The data to write write to the `write_address`.

        Returns:
            True if the write operation is successful, False otherwise.

        Examples:
            >>> c.write_memory(0x100000, b"\xff\xff\xff\xff")
            True

            >>> c.read_memory(0x100000, 4)
            b'\xff\xff\xff\xff'

            >>> c.write_memory(0x100000, bytearray(b"\x07\x00\x00\xeb"))
            True

            >>> c.read_memory(0x100000, 4)
            b'\x07\x00\x00\xeb'
        """
        write_size = len(write_contents)

        while write_size > 0:
            temp_write_size = min(
                write_size, MAX_REQUEST_DATA_SIZE - DATA_STRUCT.size
            )
            request_data = DATA_STRUCT.pack(write_address, temp_write_size)
            request_data += write_contents[:temp_write_size]
            request, request_id = self._generate_header(
                RequestType.WriteMemory, len(request_data)
            )
            request += request_data

            _ = self.socket.sendto(request, (self.address, self.port))

            try:
                raw_reply = self.socket.recv(MAX_PACKET_SIZE)
            except TimeoutError:
                return False

            reply_data = self._read_and_validate_header(
                raw_reply, request_id, RequestType.WriteMemory
            )

            if reply_data is None:
                return False

            write_address += temp_write_size
            write_size -= temp_write_size
            write_contents = write_contents[temp_write_size:]

        return True


if __name__ == "__main__":
    import doctest

    test_results = doctest.testmod(extraglobs={"c": Citra()})
    print(test_results)
