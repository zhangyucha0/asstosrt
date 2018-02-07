from __future__ import division
import sys
import re
from xml.dom.minidom import Document


if sys.version_info.major > 2:
    unicode = str  # Compatible with Py3k.

_REG_CMD = re.compile(r'{.*?}')
_WEBVTT_FORMAT = lambda srt: 'WEBVTT\r\n\n' + srt[0:]


class SrtTime(object):
    def __init__(self, string):
        """The string is like '19:89:06.04'."""
        h, m, s = string.split(':', 2)
        s, cs = s.split('.')
        self.hour = int(h)
        self.minute = int(m)
        self.second = int(s)
        # It's centisec in ASS
        self.microsecond = int(cs) * 10
        if (self.microsecond < 0):
            self.microsecond = 0


    def sort_key(self):
        """Used by sort(key=...)."""
        return (self.hour, self.minute, self.second, self.microsecond)


    def __sub__(self, other):
        return (self.hour - other.hour) * 3600 + \
                (self.minute - other.minute) * 60 + \
                (self.second - other.second) + \
                (self.microsecond - other.microsecond) / 1000


    def __str__(self):  # SRT Format
        return '{:02d}:{:02d}:{:02d},{:03d}'.format(self.hour,
                self.minute, self.second, self.microsecond)
    __unicode__ = __str__


class WebVttTime(SrtTime):
    def __str__(self):  # VTT Format
        return '{:02d}:{:02d}:{:02d}.{:03d}'.format(self.hour,
                self.minute, self.second, self.microsecond)
    __unicode__ = __str__


class AssDialogueFormater(object):
    def __init__(self, format_line):
        colums = format_line[7:].split(',')
        self._columns_names = [c.strip().lower() for c in colums]


    def format(self, dialogue_line, outputformat):
        """Return a dict whose key is from Format line
        and value is from dialogue line.
        """
        columns = dialogue_line[9:].split(',', len(self._columns_names) - 1)
        formated = {name: columns[idx] \
                    for idx, name in enumerate(self._columns_names)}

        if outputformat == 'vtt' or outputformat == 'xml':
            formated['start'] = WebVttTime(formated['start'])
            formated['end'] = WebVttTime(formated['end'])
        else:
            formated['start'] = SrtTime(formated['start'])
            formated['end'] = SrtTime(formated['end'])

        return formated


class StrDialogue(object):
    def __init__(self, time_from, time_to, text=''):
        self.time_from = time_from
        self.time_to = time_to
        self.text = text


    def __unicode__(self):
        return u'{} --> {}\r\n{}\r\n'.format(self.time_from,
                self.time_to, self.text)
    __str__ = __unicode__


def _preprocess_line(line):
    """Remove line endings and comments."""
    line = line.strip()
    if line.startswith(';'):
        return ''
    else:
        return line


def _ass_transtime(time):
    hour, minute, second = map(lambda x: float(x), time.split(':'))
    return int((hour * 3600 + minute * 60 + second) * 1000)


def _xml_format(lines):
    """Generate XML"""
    doc = Document()
    xml = doc.createElement("xml")
    doc.appendChild(xml)
    for i in lines:
        dia = _write_xml_element(doc, "dia", xml)
        _write_xml_element(doc, "st", dia, value=str(i['time'][0]))
        _write_xml_element(doc, "et", dia, value=str(i['time'][1]))
        # replace illegal bytes in content to avoid XML parse error
        # illegal bytes include <>&'\"\x00-\x08\x0b-\x0c\x0e-\x1f
        _write_xml_element(doc, "sub", dia, value=re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', i['content']),
                                cdata=True)
    return doc.toxml()[22:]  # utf-8 [38:]


def _write_xml_element(doc, name, father, value=None, cdata=False):
    if cdata is True:
        obj = doc.createElement(name)
        obj_value = doc.createCDATASection(value)
        obj.appendChild(obj_value)
        father.appendChild(obj)
        return obj
    else:
        if value is None:
            obj = doc.createElement(name)
            father.appendChild(obj)
            return obj
        elif value is not None:
            obj = doc.createElement(name)
            obj_value = doc.createTextNode(value)
            obj.appendChild(obj_value)
            father.appendChild(obj)
            return obj


def convert(file, translator=None, no_effect=False, only_first_line=False, outputformat='srt'):
    """Convert a ASS subtitles to SRT format and return the content of SRT.
    
    Arguments:
    file            -- a file-like object which shoud handle decoding;
    translator      -- a instance of LangconvTranslator or OpenCCTranslator;
    no_effect       -- delete all effect dialogues;
    only_first_line -- only keep the first line of each dialogue.

    """
    for line in file:  # Locate the Events tag.
        line = _preprocess_line(line)
        if line.startswith('[Events]'):
            break
    formater = None

    for line in file:  # Find Format line.
        line = _preprocess_line(line)
        if line.startswith('Format:'):
            formater = AssDialogueFormater(line)
            break
    if formater is None:
        raise ValueError("Can't find Events tag or Foramt line in this file.")

    # Iterate and convert all Dialogue lines:
    srt_dialogues = []
    for line in file:
        line = _preprocess_line(line)
        if line.startswith('['):
            break  # Events ended.
        elif not line.startswith('Dialogue:'):
            continue

        dialogue = formater.format(line, outputformat)
        if dialogue['end'] - dialogue['start'] < 0.2:
            continue  # Ignore duration < 0.2 second.
        if no_effect:
            if dialogue.get('effect', ''):
                continue
        if dialogue['text'].endswith('{\p0}'):  # TODO: Exact match drawing commands.
            continue


        text = ''.join(_REG_CMD.split(dialogue['text']))  # Remove commands.
        text = text.replace(r'\N', '\r\n').replace(r'\n', '\r\n')
        if only_first_line:
            text = text.split('\r\n', 1)[0]
        if translator is not None:
            text = translator.convert(text)

        if outputformat == 'xml':
            lineDic = {}
            lineDic['content'] = text
            lineDic['time'] = (_ass_transtime(str(dialogue['start'])), _ass_transtime(str(dialogue['end'])))
            srt_dialogues.append(lineDic)
        else:
            srt_dialogues.append(StrDialogue(dialogue['start'], dialogue['end'], text))

    srt = ''
    if outputformat == 'xml':
        srt = _xml_format(srt_dialogues)
    else:
        srt_dialogues.sort(key=lambda dialogue: dialogue.time_from.sort_key())
        i = 0
        for dialogue in srt_dialogues:
            i += 1
            srt += u'{}\r\n{}\r\n'.format(i, unicode(dialogue))

        if outputformat == 'vtt':
            srt = _WEBVTT_FORMAT(srt)

    return srt
