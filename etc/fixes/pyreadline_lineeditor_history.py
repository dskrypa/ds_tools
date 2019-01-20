# -*- coding: utf-8 -*-
#*****************************************************************************
#       Copyright (C) 2006  Jorgen Stenarson. <jorgen.stenarson@bostream.nu>
#
#   Edited to fix history file encoding for UTF-8.  May not be compatible with
#   Python 2.7
#
#   Intended to replace pyreadline/lineeditor/history.py
#
#*****************************************************************************
"""
pyreadline license
------------------

pyreadline is released under a BSD-type license.

Copyright (c) 2006 Jörgen Stenarson <jorgen.stenarson@bostream.nu>.

Copyright (c) 2003-2006 Gary Bishop

Copyright (c) 2003-2006 Jack Trainor

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

  a. Redistributions of source code must retain the above copyright notice,
     this list of conditions and the following disclaimer.

  b. Redistributions in binary form must reproduce the above copyright
     notice, this list of conditions and the following disclaimer in the
     documentation and/or other materials provided with the distribution.

  c. Neither the name of the copyright holders nor the names of any
     contributors to this software may be used to endorse or promote products
     derived from this software without specific prior written permission.


THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
DAMAGE.
"""

from __future__ import print_function, unicode_literals, absolute_import
import re, operator, string, sys, os

from pyreadline.unicode_helper import ensure_unicode, ensure_str
if "pyreadline" in sys.modules:
    pyreadline = sys.modules["pyreadline"]
else:
    import pyreadline

from . import lineobj

class EscapeHistory(Exception):
    pass

from pyreadline.logger import log


class LineHistory(object):
    def __init__(self):
        self.history = []
        self._history_length = 100
        self._history_cursor = 0
        self.history_filename = os.path.expanduser(ensure_str('~/.history')) #Cannot expand unicode strings correctly on python2.4
        self.lastcommand = None
        self.query = ""
        self.last_search_for = ""

    def get_current_history_length(self):
        '''Return the number of lines currently in the history.
        (This is different from get_history_length(), which returns 
        the maximum number of lines that will be written to a history file.)'''
        value = len(self.history)
        log("get_current_history_length:%d"%value)
        return value

    def get_history_length(self):
        '''Return the desired length of the history file. Negative values imply
        unlimited history file size.'''
        value = self._history_length
        log("get_history_length:%d"%value)
        return value

    def get_history_item(self, index):
        '''Return the current contents of history item at index (starts with index 1).'''
        item = self.history[index - 1]
        log("get_history_item: index:%d item:%r"%(index, item))
        return item.get_line_text()

    def set_history_length(self, value):
        log("set_history_length: old:%d new:%d"%(self._history_length, value))
        self._history_length = value

    def get_history_cursor(self):
        value = self._history_cursor
        log("get_history_cursor:%d"%value)
        return value

    def set_history_cursor(self, value):
        log("set_history_cursor: old:%d new:%d"%(self._history_cursor, value))
        self._history_cursor = value
        
    history_length = property(get_history_length, set_history_length)
    history_cursor = property(get_history_cursor, set_history_cursor)

    def clear_history(self):
        '''Clear readline history.'''
        self.history[:] = []
        self.history_cursor = 0

    def read_history_file(self, filename=None): 
        '''Load a readline history file.'''
        if filename is None:
            filename = self.history_filename
        try:
            for line in open(filename, 'r', encoding="utf-8"):
                self.add_history(lineobj.ReadLineTextBuffer(ensure_unicode(line.rstrip())))
        except IOError:
            self.history = []
            self.history_cursor = 0

    def write_history_file(self, filename = None): 
        '''Save a readline history file.'''
        if filename is None:
            filename = self.history_filename
		
        with open(filename, 'w', encoding="utf-8") as fp:
            for line in self.history[-self.history_length:]:
                fp.write(ensure_unicode(line.get_line_text()))
                fp.write('\n')

    def add_history(self, line):
        '''Append a line to the history buffer, as if it was the last line typed.'''
        line = ensure_unicode(line)
        if not hasattr(line, "get_line_text"):
            line = lineobj.ReadLineTextBuffer(line)
        if not line.get_line_text():
            pass
        elif len(self.history) > 0 and self.history[-1].get_line_text() == line.get_line_text():
            pass
        else:
            self.history.append(line)
        self.history_cursor = len(self.history)

    def previous_history(self, current): # (C-p)
        '''Move back through the history list, fetching the previous command. '''
        if self.history_cursor == len(self.history):
            self.history.append(current.copy()) #do not use add_history since we do not want to increment cursor
            
        if self.history_cursor > 0:
            self.history_cursor -= 1
            current.set_line(self.history[self.history_cursor].get_line_text())
            current.point = lineobj.EndOfLine

    def next_history(self, current): # (C-n)
        '''Move forward through the history list, fetching the next command. '''
        if self.history_cursor < len(self.history) - 1:
            self.history_cursor += 1
            current.set_line(self.history[self.history_cursor].get_line_text())

    def beginning_of_history(self): # (M-<)
        '''Move to the first line in the history.'''
        self.history_cursor = 0
        if len(self.history) > 0:
            self.l_buffer = self.history[0]

    def end_of_history(self, current): # (M->)
        '''Move to the end of the input history, i.e., the line currently
        being entered.'''
        self.history_cursor = len(self.history)
        current.set_line(self.history[-1].get_line_text())

    def reverse_search_history(self, searchfor, startpos=None):
        if startpos is None:
            startpos = self.history_cursor
        origpos = startpos

        result =  lineobj.ReadLineTextBuffer("")

        for idx, line in list(enumerate(self.history))[startpos:0:-1]:
            if searchfor in line:
                startpos = idx
                break

        #If we get a new search without change in search term it means
        #someone pushed ctrl-r and we should find the next match
        if self.last_search_for == searchfor and startpos > 0:
            startpos -= 1
            for idx, line in list(enumerate(self.history))[startpos:0:-1]:
                if searchfor in line:
                    startpos = idx
                    break

        if self.history:                    
            result = self.history[startpos].get_line_text()
        else:
            result = ""
        self.history_cursor = startpos
        self.last_search_for = searchfor
        log("reverse_search_history: old:%d new:%d result:%r"%(origpos, self.history_cursor, result))
        return result
        
    def forward_search_history(self, searchfor, startpos=None):
        if startpos is None:
            startpos = min(self.history_cursor, max(0, self.get_current_history_length()-1))
        origpos = startpos
        
        result =  lineobj.ReadLineTextBuffer("")

        for idx, line in list(enumerate(self.history))[startpos:]:
            if searchfor in line:
                startpos = idx
                break

        #If we get a new search without change in search term it means
        #someone pushed ctrl-r and we should find the next match
        if self.last_search_for == searchfor and startpos < self.get_current_history_length()-1:
            startpos += 1
            for idx, line in list(enumerate(self.history))[startpos:]:
                if searchfor in line:
                    startpos = idx
                    break

        if self.history:                    
            result = self.history[startpos].get_line_text()
        else:
            result = ""
        self.history_cursor = startpos
        self.last_search_for = searchfor
        return result

    def _search(self, direction, partial):
        try:
            if (self.lastcommand != self.history_search_forward and
                    self.lastcommand != self.history_search_backward):
                self.query = ''.join(partial[0:partial.point].get_line_text())
            hcstart = max(self.history_cursor,0) 
            hc = self.history_cursor + direction
            while (direction < 0 and hc >= 0) or (direction > 0 and hc < len(self.history)):
                h = self.history[hc]
                if not self.query:
                    self.history_cursor = hc
                    result = lineobj.ReadLineTextBuffer(h, point=len(h.get_line_text()))
                    return result
                elif (h.get_line_text().startswith(self.query) and (h != partial.get_line_text())):
                    self.history_cursor = hc
                    result = lineobj.ReadLineTextBuffer(h, point=partial.point)
                    return result
                hc += direction
            else:
                if len(self.history) == 0:
                    pass 
                elif hc >= len(self.history) and not self.query:
                    self.history_cursor = len(self.history)
                    return lineobj.ReadLineTextBuffer("", point=0)
                elif self.history[max(min(hcstart, len(self.history) - 1), 0)]\
                        .get_line_text().startswith(self.query) and self.query:
                    return lineobj.ReadLineTextBuffer(self.history\
                            [max(min(hcstart, len(self.history) - 1),0)],
                                point = partial.point)
                else:                
                    return lineobj.ReadLineTextBuffer(partial, 
                                                      point=partial.point)
                return lineobj.ReadLineTextBuffer(self.query, 
                                                  point=min(len(self.query),
                                                  partial.point))
        except IndexError:
            raise

    def history_search_forward(self, partial): # ()
        '''Search forward through the history for the string of characters
        between the start of the current line and the point. This is a
        non-incremental search. By default, this command is unbound.'''
        q= self._search(1, partial)
        return q

    def history_search_backward(self, partial): # ()
        '''Search backward through the history for the string of characters
        between the start of the current line and the point. This is a
        non-incremental search. By default, this command is unbound.'''
        
        q= self._search(-1, partial)
        return q

if __name__ == "__main__":
    q = LineHistory()
    r = LineHistory()
    s = LineHistory()
    RL = lineobj.ReadLineTextBuffer
    q.add_history(RL("aaaa"))
    q.add_history(RL("aaba"))
    q.add_history(RL("aaca"))
    q.add_history(RL("akca"))
    q.add_history(RL("bbb"))
    q.add_history(RL("ako"))
    r.add_history(RL("ako"))
