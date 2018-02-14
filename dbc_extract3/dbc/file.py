import os, logging, io

import dbc, dbc.wdc1, dbc.xfth

_PARSERS = {
    b'WDC1': dbc.wdc1.WDC1Parser
}

class HotfixIterator:
    def __init__(self, f, wdb_parser):
        self._data_class = getattr(dbc.data, wdb_parser.class_name().replace('-', '_'))
        self._parser = f.parser
        self._wdb_parser = wdb_parser
        self._records = f.parser.n_entries(wdb_parser)

        self._record = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._record == self._records:
            raise StopIteration

        dbc_id, record_id, offset, size, key_id = self._parser.get_record_info(self._record, self._wdb_parser)
        data = self._parser.get_record(dbc_id, offset, size, self._wdb_parser)

        # If the cache entry is for a WDB file that is expanded, we need to
        # separate the record id and the key block id from the parsed data,
        # since they are included as the first and last element of the parsed
        # tuple, respectively
        #
        # TODO: Can we have key blocks in hotfix data somehow other than as an expanded record?
        if self._wdb_parser.class_name() in dbc.EXPANDED_HOTFIX_RECORDS:
            start_offset = 0
            end_offset = len(data)
            # If id block is used, and the cache entry for the db file uses an
            # expanded parser, the id will be the first entry of the data.
            # Strip it out, since we already have the id elsewhere in the hotfix entry
            if self._wdb_parser.has_id_block():
                start_offset += 1

            # If the key block is used, and the cache entry for the db file
            # uses an  expanded parser, the key id (parent id) will be the last
            # entry of the data. Extract it out and pass it to the decorator
            if self._wdb_parser.has_key_block():
                key_id = data[-1]
                end_offset -= 1

            data = data[start_offset:end_offset]

        self._record += 1

        return self._data_class(self._parser, dbc_id, data, key_id)

class HotfixFile:
    def __init__(self, options):
        self.options = options
        self.parser = dbc.xfth.XFTHParser(options)

    def open(self):
        if not self.parser.open():
            return False

        return True

    # Hotfix cache has to be accessed with a specific WDB file parser to get
    # the record layout (and the correct hotfix entries).
    def entries(self, wdb_parser):
        return HotfixIterator(self, wdb_parser)

class DBCFileIterator:
    def __init__(self, f):
        self._parser = f.parser
        self._decorator = f.record_class

        self._record = 0
        self._n_records = self._parser.n_records()

    def __iter__(self):
        return self

    def __next__(self):
        if self._record == self._n_records:
            raise StopIteration

        dbc_id, record_id, offset, size, key_id = self._parser.get_record_info(self._record)
        data = self._parser.get_record(dbc_id, offset, size)

        self._record += 1

        return self._decorator(self._parser, dbc_id, data, key_id)

class DBCFile:
    def __init__(self, options, filename):
        self.data_class = None
        self.options = options
        self.file_name = filename

    def class_name(self):
        return os.path.basename(self.file_name).split('.')[0]

    def record_class(self, *args):
        if self.data_class:
            if len(args) > 0:
                return self.data_class(*args)
            else:
                return self.data_class

        try:
            if not self.options.raw:
                self.data_class = getattr(dbc.data, self.class_name().replace('-', '_'))
            else:
                self.data_class = dbc.data.RawDBCRecord
        except KeyError:
            logging.warn("Unable to determine data format for %s ...", self.class_name())
            self.data_class = dbc.data.RawDBCRecord

        if len(args) > 0:
            return self.data_class(*args)
        else:
            return self.data_class

    def open(self):
        f = None
        # See that file exists already
        normalized_path = os.path.abspath(self.file_name)
        real_path = None
        for i in ['', '.db2']:
            if os.access(normalized_path + i, os.R_OK):
                real_path = normalized_path + i
                break

        if not real_path:
            logging.error('Unable to find DBC file through %s', self.file_name)
            return False

        with io.open(real_path, 'rb') as f:
            magic = f.read(4)
            parser = _PARSERS.get(magic, None)
            if not parser:
                logging.error('No parser found for file format "%s"', magic.decode('utf-8'))
                return False

            self.parser = parser(self.options, self.file_name)

        return self.parser.open()

    def find(self, dbc_id):
        info = self.parser.get_dbc_info(dbc_id)
        if info.dbc_id != dbc_id:
            return None

        data = self.parser.get_record(info.dbc_id, info.record_offset, info.record_size)
        if len(data) > 0:
            return self.record_class(self.parser, info.dbc_id, data, info.parent_id)
        else:
            return None

    def __iter__(self):
        return DBCFileIterator(self)

    def __str__(self):
        return str(self.parser)

