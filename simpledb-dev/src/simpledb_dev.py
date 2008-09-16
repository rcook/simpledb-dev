#!/usr/bin/python

#===============================================================================
#
# 
# SimpleDB/dev allows you to develop from SimpleDB locally. 
# Currently implemented is the REST API.
#
# Copyright Matthew Painter 2008
#
# http://code.google.com/p/simpledb-dev/
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# To run:       python simpledb_dev.py <port>
# To run tests: python simpledb_dev.py test
#===============================================================================

import sys, os, time, re, base64, pickle, uuid, web, fcntl

MAX_DOMAINS = 100
DATA_DIR = os.path.realpath('domains/')

# For debugging use only
web.internalerror = web.debugerror

render = web.template.render('templates/', cache=False)

urls = (
    '/', 'SimpleDBDevDispatcher'
)


def getRequestId():
    '''Return a request id.'''
    return uuid.uuid4()

class SimpleDBDevDispatcher:
    ''' This class is the web.py dispatcher '''
    
    def GET(self):
        
        web.header("Content-Type","text/xml charset=utf-8")
        
        input = web.input()
        action = input.get('Action', '')
        
        # Check not a private method (prefix _) and that action, i.e. method, exists
        if not re.compile('^[A-Z]').match(action) or SimpleDBDevRenderer.__dict__.get(action,None) is None:
            action = ''
            
        # TODO: not sure what the response is for an action not existing
        if action == '':
            web.ctx.status = '400 Bad Request'
            output = render.error('NoSuchAction', "The action " + input.get('Action', '') + " is not valid for this web service.", getRequestId())
        else:
            try :
                output = SimpleDBDevRenderer.__dict__[action].__get__(SimpleDBDevRenderer(), SimpleDBDevRenderer)(input)
            except SimpleDBError, e:
                web.ctx.status = e.httpStatus
                output = render.error(e.errorCode, e.msg, e.requestId)
                
        print output

class SimpleDBDevRenderer:
    ''' Calls the SimpleDBDev API and renders the results. '''
    
    def CreateDomain(self, input):
        requestId = SimpleDBDev().CreateDomain(input)
        return render.CreateDomain(requestId)
    
    def DeleteDomain(self, input):
        requestId = SimpleDBDev().DeleteDomain(input)
        return render.DeleteDomain(requestId)
        
    def ListDomains(self, input):
        selectedDomains, nextTokenNow, requestId = SimpleDBDev().ListDomains(input)
        return render.ListDomains(selectedDomains, nextTokenNow, requestId)
        
    def PutAttributes(self, input):
        requestId = SimpleDBDev().PutAttributes(input)
        return render.PutAttributes(requestId)
        
    def DeleteAttributes(self, input):
        requestId = SimpleDBDev().PutAttributes(input)
        return render.DeleteAttributes(requestId)

    def GetAttributes(self, input):
        item, requestId = SimpleDBDev().GetAttributes(input)
        return render.GetAttributes(item, requestId)
  
    def Query(self, input):
        selectedKeys, nextTokenNow, requestId = SimpleDBDev().Query(input)
        return render.Query(selectedKeys, nextTokenNow, requestId)

    def QueryWithAttributes(self, input):
        items, nextTokenNow, requestId = SimpleDBDev().QueryWithAttributes(input)
        return render.QueryWithAttributes(items, nextTokenNow, requestId)
    
class SimpleDBDev:
    
    ''' The API to our local server. '''
        
    def _error(self, code, httpStatus, msg = ''):
        raise SimpleDBError(getRequestId(), httpStatus, code, msg)
    
    def _getDomainFile(self, domainName, checkExists = False):
        file = os.path.join(DATA_DIR, base64.b64encode(domainName) )
        if checkExists and not os.path.exists(file):
            self._error('NoSuchDomain', '400 Bad Request', 'The specified domain does not exist.')
        return file
    
    def _getDomainName(self, input):
        domainName = input.get('DomainName', '')
        if domainName == '':
            self._error('MissingParameter', '400 Bad Request', 'The request must contain the parameter DomainName.')
        if domainName.__len__() > 1024  :
            self._error('InvalidParameterValue',  '400 Bad Request', "Value (" + domainName + ") for parameter Value is invalid. Value exceeds maximum length of 1024.")
        return domainName

    def _encodeNextToken(self, i):
        if i is None:
            return None
        return base64.b64encode('THIS IS PADDING '+str(i))
    
    def _decodeNextToken(self, str):
        if str is None or str == '':
            return 0
        s = base64.b64decode(str)
        p = re.compile('^THIS IS PADDING ([0-9]+)$')
        x = p.match(s).group(1)
        if x is None:
            self._error('InvalidNextToken', '400 Bad Request', 'The specified next token is not valid.')
        return int(x)
    
    def CreateDomain(self, input):
        domainName = self._getDomainName(input)
        domainFile = self._getDomainFile(domainName)
        
        domainNames = self._getDomainNames()
        if len(domainNames) > MAX_DOMAINS:
            self._error('NumberDomainsExceeded', '409 Conflict', 'The domain limit was exceeded.')
        
        if not os.path.exists(domainFile):
            f = open(domainFile, "w")
            pickle.dump({'name': domainName, 'data': {}}, f)
            f.close()
        return getRequestId()
	
    def DeleteDomain(self, input):
        domainName = self._getDomainName(input)
        domainFile = self._getDomainFile(domainName)
        if os.path.exists(domainFile):
            os.unlink(domainFile)
        return getRequestId()
    
    def _getOffset(self, input):
        nextToken = input.get('NextToken', None)
        return self._decodeNextToken(nextToken)
    
    def _getDomainNames(self):
        domainNames = []
        for file in os.listdir(DATA_DIR):
            if str(file).endswith('.lock') or str(file).startswith('.'): 
                continue
            domainNames.append(base64.b64decode(file))
        return domainNames
    
    def _getSlice(self, offset, max, list):
        
        l = len(list)
        
        count = l-offset
        
        if count >  max :
            count = max

        if count + offset < l:
            nextToken = self._encodeNextToken(offset + count)
        else :
            nextToken = None
        
        slice = list[offset:offset+count]
        
        return nextToken, slice
    
    def ListDomains(self, input):

        maxNumberOfDomains = int(input.get('MaxNumberOfDomains', 100))
        
        if maxNumberOfDomains < 1 or maxNumberOfDomains > 100 :
            self._error('InvalidParameterValue', '400 Bad Request', "Value (" + maxNumberOfDomains + ") for parameter MaxNumberOfDomains is invalid. MaxNumberOfDomains must be between 1 and 100." )
        
        offset = self._getOffset(input)
        
        domainNames = self._getDomainNames()
        
        nextToken, domains = self._getSlice(offset, maxNumberOfDomains, domainNames)

        return domains, nextToken, getRequestId()
        
    def _getString(self, input, name):
        value = input.get(name, '')
        if value == '':
            self._error('MissingParameter', '400 Bad Request', "The request must contain the parameter "+name) 

        if value.__len__() > 1024  :
            self._error('InvalidParameterValue', '400 Bad Request', "Value (" + value + ") for parameter Value is invalid. Value exceeds maximum length of 1024.")
        return value
        
    def _changeData(self, domainFile, input, function):
        
        # We want a block until the lock is released
        lockf = open(domainFile+'.lock', "w")
        fcntl.lockf(lockf.fileno(), fcntl.LOCK_EX)
        
        # read in the domain data
        domainData = self._getDomainData(domainFile)
        
        ret = function(domainData, input)
        
        # dump it out
        tempf = open(domainFile+'.tmp', "w")
        pickle.dump(domainData, tempf)
        tempf.close()
        
        # atomic move
        os.rename(domainFile+'.tmp', domainFile)
    
        # release the lock
        lockf.close()
        
        return ret
        
    def PutAttributes(self, input):
        
        domainName = self._getDomainName(input)
        domainFile = self._getDomainFile(domainName, True)
        
        return self._changeData(domainFile, input, self._PutAttributes)

    def _PutAttributes(self, domainData, input):

        itemName = self._getString(input, 'ItemName')

        # This is our item
        item = domainData['data'].get(itemName, {})
         
        # Now we have to get the attribute info from the request
        r = re.compile('^Attribute\.([0-9]+)\.([A-Z][a-z]+)$')
        
        a = self._extractAttributeInput(input)
        
        replacesIndexes = []
        for i in a :     
            if a[i].get('Replace', 'false') == 'true':
                replacesIndexes.append(i)

        #Let's delete all the values that we are replacing
        for i in replacesIndexes:
            aname = a[i]['Name']
            if item.get(aname, None) is not None:
                del item[aname]

        for i in a:
            aname = a[i]['Name']
            if a[i]['Value'].__len__() > 1024  :
                self._error('InvalidParameterValue', '400 Bad Request', "Value (" + a[i]['Value'] + ") for parameter Value is invalid. Value exceeds maximum length of 1024.")
            avalueNow = item.get(aname, None)
            if avalueNow is None :
                item[aname] = [ a[i]['Value'] ]
            else: # list
                if not a[i]['Value'] in avalueNow :
                    avalueNow.append(a[i]['Value'])
        
        # refresh our domain data
        domainData['data'][itemName] = item
        
        return getRequestId()
        
    def _extractAttributeInput(self, input):
        # Now we have to get the attribute info from the request
        r = re.compile('^Attribute\.([0-9]+)\.([A-Z][a-z]+)$')
        
        a = {}
        for l in input :
            match = r.match(l)
            if match is None:
                continue
            i = match.group(1)
            v = match.group(2)
            
            if a.get(i, None) is None:
                a[i] = {}
                
            if v == 'Replace' and (input[l] != 'true' and input[l] != 'false') :
                self._error(InvalidParameterValue, '400 Bad Request', "Value (" + input[l] + ") for parameter Replace is invalid. The Replace flag should be either true or false." )
                
            a[i][v] = input[l]
            
        for i in a:
            if a[i].get('Name', '') == '' :
                self._error('MissingParameter', '400 Bad Request', "Attribute.Name missing for Attribute "+i)
            if a[i].get('Value', '') == '' :
                self._error('MissingParameter', '400 Bad Request', "Attribute.Value missing for Attribute "+i)
            
        return a
        
    def DeleteAttributes(self, input):
        
        domainName = self._getDomainName(input)
        domainFile = self._getDomainFile(domainName, True)
        
        return self._changeData(domainFile, input, self._DeleteAttributes)
        
    def _DeleteAttributes(self, domainData, input):

        itemName = self._getString(input, 'ItemName')

        # This is our item
        item = domainData['data'].get(itemName, {})
        
        a = self._extractAttributeInput(input)
        
        for i in a:
            aname = a[i]['Name']
            avalueNow = item.get(aname, None)
            if avalueNow is not None : # list
                try :
                    avalueNow.remove(a[i]['Value'])
                    if avalueNow.__len__() == 0 :
                        del item[aname]
                except:
                    pass
        
        # refresh our domain data
        if item.__len__() == 0 :
            del domainData['data'][itemName] 
        else :
            domainData['data'][itemName] = item
        
        return getRequestId()

    def _getDomainData(self, domainFile):
        # read in the domain data
        f = open(domainFile, "r")
        domainData = pickle.load(f)
        f.close()
        return domainData

    def GetAttributes(self, input):
        itemName = self._getString(input, 'ItemName')
        domainName = self._getDomainName(input)
        domainFile = self._getDomainFile(domainName, True)
        domainData = self._getDomainData(domainFile)
        
        # This is our item
        item = domainData['data'].get(itemName, {})
        
        return item, getRequestId()
    
    def Query(self, input):
        keys, domainData, nextToken, requestId = self._Query(input)
        return keys, nextToken, requestId
    
    def QueryWithAttributes(self, input):
        keys, domainData, nextToken, requestId = self._Query(input)
    
        items = {}
        
        for key in keys :
            items[key] = domainData['data'][key]
        
        return items, nextToken, requestId
    
    
    def _Query(self, input):

        maxNumberOfItems = int(input.get('MaxNumberOfItems', 100))
        
        if maxNumberOfItems < 1 or maxNumberOfItems > 250 :
            self._error('InvalidParameterValue', '400 Bad Request', "Value (" + maxNumberOfItems + ") for parameter MaxNumberOfItems is invalid. MaxNumberOfItems must be between 1 and 250." )
        
        queryExpression = input.get('QueryExpression', '')
        domainName = self._getDomainName(input)
        domainFile = self._getDomainFile(domainName, True)
        domainData = self._getDomainData(domainFile) 
        offset     = self._getOffset(input)
        
        if queryExpression == '':
            matchingKeys = domainData['data'].keys()
        else:
            matchingKeys = QueryTokenizer(queryExpression).run(domainData['data'])
        
        nextToken, keys = self._getSlice(offset, maxNumberOfItems, matchingKeys)

        return keys, domainData, nextToken, getRequestId()
    
class SimpleDBError(Exception):
    requestId = None
    errorCode = None
    msg = None
    httpStatus = None
    
    def __init__(self, requestId, httpStatus, errorCode, msg):
        self.httpStatus = httpStatus
        self.requestId = requestId
        self.errorCode = errorCode
        self.msg = msg

class QueryTokenizer:
    
    ''' Tokenizes and runs AWS queries. '''
    
    q = None
    sort = None
    strings = None
    predicates = None
    predicateAttributes = None
    
    stringToken = str(uuid.uuid4())
    predicateToken = str(uuid.uuid4())
    
    compOps = ["starts-with","does-not-start-with","=","<",">","<=",">=","!="]
    
    def __init__(self, query):
        '''Process the query.'''
        self.predicateAttributes = {}
        self.strings = []
        self.predicates = []
        self.q = query
        self._processStrings()
        self._processPredicates()
        self.q = self.q.split()
        self._processSort()

    def _error(self, httpStatus, code, msg = ''):
        raise SimpleDBError(getRequestId(), httpStatus, code, msg)

    def _invalidQuery(self):
        self._error('InvalidQueryExpression', '400 Bad Request', 'The specified query expression syntax is not valid.')

    def _processSort(self):
        if 'sort' in self.q:
            i = self.q.index('sort')
            q = self.q
            self.q = q[0:i]
            self.sort = q[i+1:]
            l = len(self.sort)
            
            if self.sort[0] != self.stringToken:
                self._invalidQuery()
                
            if l == 0 or l > 3 :
                self._invalidQuery()
                
            elif l==3 :
                if self.sort[2] != 'asc' and self.sort[2] != 'desc' :
                    self._invalidQuery()
            else :
                self.sort.append('asc')
                
            s = self.sort
            
            self.sort = [self.strings[int(s[1])], s[2]]

    def run(self, input):
        result = {}
        tokens = self.q[:]
        setOp = 'union'
        
        tokenIterator = iter(tokens)
        predicateIterator = iter(self.predicates)

        try:
            while True:

                negate = False
                token = tokenIterator.next()
                
                if ( token == 'not' ) :
                    negate = True
                    token = tokenIterator.next()
                if ( token != self.predicateToken ):
                    self._invalidQuery()
                
                predicate = predicateIterator.next()
                
                
                
                if setOp == 'union' :
                    for name in input :
                        if result.get(name, None) is not None:
                            continue
                        pTrue = self._predicateTrue(input[name], predicate)
                        if (pTrue and not negate) or (not pTrue and negate):
                            result[name] = True
                else :
                    dels = []
                    for name in result :
                        pTrue = self._predicateTrue(input[name], predicate)
                        if (pTrue and negate) or (not pTrue and not negate):
                            dels.append(name)
                    for name in dels :
                        del result[name]
                    
                try:
                    setOp =  tokenIterator.next()
                    if setOp != 'union' and setOp != 'intersection' :
                        SimpleDBError('Expected union or intersection')
                except StopIteration:
                    if self.sort is None:
                        return result.keys()
                    return self._doSort(result, input)
                
        except StopIteration:
            self._invalidQuery()

    def _doSort(self, result, input):

        attribute = self.sort[0]
        direction = self.sort[1]
        
        rev_items = [(input[k].get(attribute,None), k) for k, v in result.items()]
        rev_items.sort(reverse=(direction == 'desc'))
        return [k for (v, k) in rev_items]
        
    def _predicateTrue(self, item, predicate):

        maxI = len(predicate) - 1
        logicOp = None
        result = True
        identifier = predicate[0]
        
        value = item.get(identifier, None)
            
        if value is None :
            return False

        for v in value:
        
            i = 0
        
            while True:
                
                if identifier != predicate[i]:
                    self._invalidQuery()
    
                
                i+=1
                compFn = predicate[i]
                i+=1
                constant = predicate[i]
                i+=1

                r = compFn(v, constant)

                if logicOp is None :
                    result = r
                elif logicOp == 'or' :
                    result = result or r
                else :
                    result = result and r
                            
                if i > maxI:
                    if result:
                        return True
                    break
    
                logicOp = predicate[i]
                i+=1
                
        return False
          
    def _processStrings(self):
        rexp = "'((?:\\\\\\\\|\\\\'|[^'])*)'"
        r = re.compile(rexp)
        while True:
            q = r.sub(self._processString, self.q)
            if q == self.q:
                break
            self.q = q
    
    def _processPredicates(self):
        rexp = "\[\s*([^\]]+)\s*\]"
        r = re.compile(rexp)
        while True:
            q = r.sub(self._processPredicate, self.q)
            if q == self.q:
                break
            self.q = q

    def _processPredicate(self, match):
        string = match.group(1)
        predicate = string.split()
        p = []
        predicateIterator = iter(predicate)
        try:
            while True:

                stringToken = predicateIterator.next()

                if stringToken != self.stringToken :
                    self._invalidQuery()

                identifierIndex = int(predicateIterator.next())
                identifier = self.strings[identifierIndex]
                p.append(identifier)
                self.predicateAttributes[identifier] = True
                
                compOp = predicateIterator.next()
                
                if not compOp in self.compOps :
                    self._invalidQuery()

                if compOp == '=':
                    compFn = lambda value, constant: (value == constant)
                elif compOp == '>':
                    compFn = lambda value, constant: value > constant
                elif compOp == '<':
                    compFn = lambda value, constant: value < constant
                elif compOp == '=':
                    compFn = lambda value, constant: value == constant
                elif compOp == '!=':
                    compFn = lambda value, constant: value != constant
                elif compOp == '>=':
                    compFn = lambda value, constant: value >= constant
                elif compOp == '<=':
                    compFn = lambda value, constant: value <= constant
                elif compOp == 'starts-with':
                    compFn = lambda value, constant: value.startswith(constant)
                elif compOp == 'does-not-start-with':
                    compFn = lambda value, constant: not value.startswith(constant)
                
                p.append(compFn)
                
                stringToken = predicateIterator.next()

                stringIndex = int(predicateIterator.next())
                p.append(self.strings[stringIndex])
                
                if stringToken != self.stringToken :
                    self._invalidQuery()
                            
                try:
                
                    andOr = predicateIterator.next()
                    p.append(andOr)
                    
                    if andOr != 'and' and andOr != 'or':
                        self._invalidQuery()
                        
                except StopIteration:
                    self.predicates.append(p)
                    return ' '+self.predicateToken+' '
                
        except StopIteration:
            self._invalidQuery()
    
    def _processString(self, match):
        string = match.group(1)
        r = re.compile("\\\\'")
        string = r.sub("'", string)
        r = re.compile("\\\\\\\\")
        string = r.sub('\\\\', string)
        self.strings.append(string)
        return ' '+self.stringToken+' '+str(len(self.strings)-1)+' '
    
class SimpleDBTest():
    '''Tests taken from the SimpleDB technical documentation.'''

    domain = 'TestDomain'

    def run(self):
        
        print "\nRunning tests and printing out sample XML output...\n"
        
        self.checkData()
        self.testDeleteDomain()
        self.testCreateDomain()
        self.testPutAttributes()
        self.testGetAttributes()
        self.testQuery()
        self.testQueryWithAttributes()
        self.testDeleteAttributes()
        self.testPutAttributesReplace()
        self.testListDomains()
        self.testDeleteDomain()
        
        print "\nOK\n"

    def testDeleteAttributes(self):
        
        SimpleDBDev().DeleteAttributes({'DomainName' : self.domain, 'ItemName' : '1579124585', 
                                        'Attribute.0.Name' : 'Title', 'Attribute.0.Value' : 'The Right Stuff',
                                        'Attribute.1.Name' : 'Pages', 'Attribute.1.Value' : '00304'})
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Title' = 'The Right Stuff']"})
        assert list == []
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Pages' < '00320']"})
        assert sorted(list) == sorted(['0802131786'])
        assert NextToken is None
        
        print "Sample DeleteAttributes:\n"
        print SimpleDBDevRenderer().Query({'DomainName' : self.domain, 'QueryExpression': "['Pages' < '00320']"})
        
    def testListDomains(self):
        domains, nextToken, requestId = SimpleDBDev().ListDomains({'DomainName' : self.domain})
        assert domains == [self.domain]
        
        domain2 = self.domain+'XXX'
        
        print "Sample CreateDomain:\n"
        print SimpleDBDevRenderer().CreateDomain({'DomainName' : domain2})

        domains, nextToken, requestId = SimpleDBDev().ListDomains({'DomainName' : self.domain})
        assert sorted(domains) == sorted([self.domain, domain2])
        
        domains, nextToken, requestId = SimpleDBDev().ListDomains({'DomainName' : self.domain, 'MaxNumberOfDomains': '1'})
        assert domains == [self.domain]
        
        domains, nextToken, requestId = SimpleDBDev().ListDomains({'DomainName' : self.domain, 'NextToken' : nextToken, 'MaxNumberOfDomains': '1'})
        assert domains == [domain2]
        
        print "Sample ListDomains:\n"
        print SimpleDBDevRenderer().ListDomains({'DomainName' : self.domain})
        
        print "Sample DeleteDomain:\n"
        print SimpleDBDevRenderer().DeleteDomain({'DomainName' : domain2})
        
    def testPutAttributesReplace(self):
        
        s = SimpleDBDev()
        
        input = {
                 'ItemName' : 'B00005JPLW',
                 'DomainName' : self.domain,
                 'Attribute.0.Name' : 'Rating', 'Attribute.0.Value' : '*****', 'Attribute.0.Replace' : 'true'
                 }

        s.PutAttributes(input)
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Rating' = '*****']"})
        assert sorted(list) == sorted(['0385333498', 'B00005JPLW', 'B000SF3NGK'])
        assert NextToken is None

        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Rating' = '***']"})
        assert sorted(list) == sorted([])
        assert NextToken is None
        
        print "Sample PutAttributes:\n"
        print SimpleDBDevRenderer().PutAttributes(input)

    def testQueryWithAttributes(self):
        
        items, NextToken, requestId = SimpleDBDev().QueryWithAttributes({'DomainName' : self.domain, 'QueryExpression': "['Title' = 'The Right Stuff']"})
        assert NextToken is None
        item = items.get('1579124585', None)
        assert item is not None
        
        expected = {
                  'Title' : ['The Right Stuff'], 
                  'Author' : ['Tom Wolfe'], 
                  'Year' : ['1979'], 
                  'Pages' : ['00304'],
                  'Keyword' : ['Book', 'Hardcover', 'American'],
                  'Rating' : ['****', '4 stars']
                }
        
        for key in expected :
            assert sorted(item[key]) == sorted(expected[key]) 
            
        print "Sample QueryWithAttributes:"
        print SimpleDBDevRenderer().QueryWithAttributes({'DomainName' : self.domain, 'QueryExpression': "['Title' = 'The Right Stuff']"})
        
    def testQuery(self):
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain})
        assert list == ['B000T9886K', '1579124585', '0385333498', '0802131786', 'B00005JPLW', 'B000SF3NGK']
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Title' = 'The Right Stuff']"})
        assert list == ['1579124585']
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Year' > '1985']"})
        assert sorted(list) == sorted(['B000T9886K', 'B00005JPLW', 'B000SF3NGK'])
        assert NextToken is None

        # test next token
        list, NextToken, requestId = SimpleDBDev().Query({'MaxNumberOfItems' : '2', 'DomainName' : self.domain, 'QueryExpression': "['Year' > '1985']"})
        list2, NextToken2, requestId2 = SimpleDBDev().Query({'MaxNumberOfItems' : '2', 'NextToken' : NextToken, 'DomainName' : self.domain, 'QueryExpression': "['Year' > '1985']"})
        list2.extend(list)
        assert sorted(list2) == sorted(['B000T9886K', 'B00005JPLW', 'B000SF3NGK'])
        assert NextToken2 is None

        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Rating' starts-with '****']"})
        assert sorted(list) == sorted(['0385333498', '1579124585', '0802131786', 'B000SF3NGK'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Pages' < '00320']"})
        assert sorted(list) == sorted(['1579124585', '0802131786'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Year' > '1975' and 'Year' < '2008']"})
        assert sorted(list) == sorted(['1579124585', 'B000T9886K', 'B00005JPLW', 'B000SF3NGK'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Rating' = '***' or 'Rating' = '*****']"})
        assert sorted(list) == sorted(['0385333498', 'B00005JPLW', 'B000SF3NGK'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Year' > '1950' and 'Year' < '1960' or 'Year' starts-with '193' or 'Year' = '2007']"})
        assert sorted(list) == sorted(['0385333498', '0802131786', 'B000T9886K', 'B00005JPLW'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Rating' = '4 stars' or 'Rating' = '****']"})
        assert sorted(list) == sorted(['1579124585', '0802131786', 'B000T9886K'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Keyword' = 'Book' and 'Keyword' = 'Hardcover'] "})
        assert list == []
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Keyword' != 'Book']"})
        assert sorted(list) == sorted(['0385333498','1579124585','B000T9886K','B00005JPLW'])
        assert NextToken is None

        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Keyword' = 'CD'] intersection ['Year' = '2007']"})
        assert sorted(list) == sorted(['B000T9886K'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Keyword' = 'Frank Miller'] union ['Rating' starts-with '****'] "})
        assert sorted(list) == sorted(['0385333498','0802131786','1579124585','B00005JPLW','B000SF3NGK'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Year' >= '1900' and 'Year' < '2000'] intersection ['Keyword' = 'Book'] intersection ['Rating' starts-with '4' or 'Rating' = '****'] union ['Title' = '300'] union ['Author' = 'Paul Van Dyk'] "})
        assert sorted(list) == sorted(['0802131786','1579124585','B00005JPLW','B000T9886K'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "not ['Rating' starts-with '*'] intersection ['Year' > '2000']"})
        assert sorted(list) == sorted(['B000T9886K'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Year' < '1980'] sort 'Year' asc"})
        assert sorted(list) == sorted(['0802131786','0385333498','1579124585'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Year' < '1980'] sort 'Year'"})
        assert sorted(list) == sorted(['0802131786','0385333498','1579124585'])
        assert NextToken is None
        
        list, NextToken, requestId = SimpleDBDev().Query({'DomainName' : self.domain, 'QueryExpression': "['Year' = '2007'] intersection ['Author' starts-with ''] sort 'Author' desc"})
        assert sorted(list) == sorted(['B00005JPLW','B000T9886K'])
        assert NextToken is None
        
        print "Sample Query:\n"
        print SimpleDBDevRenderer().Query({'DomainName' : self.domain, 'QueryExpression': "['Year' = '2007'] intersection ['Author' starts-with ''] sort 'Author' desc"})
        
    def checkData(self):
        domains, nextToken, requestId = SimpleDBDev().ListDomains({'DomainName' : self.domain})
        
        if len(domains) > 1 or ( len(domains) == 1 and domains[0] != self.domain):
            raise Exception('Please make sure you have cleared the domains directory')
        
    def testDeleteDomain(self):
        SimpleDBDev().DeleteDomain({'DomainName' : self.domain})
        
        domains, nextToken, requestId = SimpleDBDev().ListDomains({'DomainName' : self.domain})
        assert not (self.domain in domains)

    def testCreateDomain(self):
        SimpleDBDev().CreateDomain({'DomainName' : self.domain})
        
        domains, nextToken, requestId = SimpleDBDev().ListDomains({'DomainName' : self.domain})
        assert self.domain in domains
        
    def _convertAttrs(self, attrs, dict):
        i = 0
        for name in attrs:
            for item in attrs[name]:
                dict['Attribute.'+str(i)+'.Name'] = name
                dict['Attribute.'+str(i)+'.Value'] = item
                i+=1
        
    def testGetAttributes(self):
        item, requestId = SimpleDBDev().GetAttributes({'DomainName' : self.domain, 'ItemName' : '0385333498'})
                                                       
        expected = {
                          'Title' : ['The Sirens of Titan'], 
                          'Author' : ['Kurt Vonnegut'], 
                          'Year' : ['1959'], 
                          'Pages' : ['00336'],
                          'Keyword' : ['Book', 'Paperback'],
                          'Rating' : ['*****', '5 stars', 'Excellent']
                        }
        
        for key in expected :
            assert sorted(item[key]) == sorted(expected[key]) 
            
        print "Sample GetAttributes:\n"
        print SimpleDBDevRenderer().GetAttributes({'DomainName' : self.domain, 'ItemName' : '0385333498'})
        
    def testPutAttributes(self):
        
        inserts =[ 
                    [
                        '0385333498',
                        {
                          'Title' : ['The Sirens of Titan'], 
                          'Author' : ['Kurt Vonnegut'], 
                          'Year' : ['1959'], 
                          'Pages' : ['00336'],
                          'Keyword' : ['Book', 'Paperback'],
                          'Rating' : ['*****', '5 stars', 'Excellent']
                        }
                    ],
                    [
                        '0802131786',
                        {
                          'Title' : ['Tropic of Cancer'], 
                          'Author' : ['Henry Miller'], 
                          'Year' : ['1934'], 
                          'Pages' : ['00318'],
                          'Keyword' : ['Book'],
                          'Rating' : ['****']
                        }
                    ],
                    [
                        '1579124585',
                        {
                          'Title' : ['The Right Stuff'], 
                          'Author' : ['Tom Wolfe'], 
                          'Year' : ['1979'], 
                          'Pages' : ['00304'],
                          'Keyword' : ['Book', 'Hardcover', 'American'],
                          'Rating' : ['****', '4 stars']
                        }
                    ],
                    [
                        'B000T9886K',
                        {
                          'Title' : ['In Between'], 
                          'Author' : ['Paul Van Dyk'], 
                          'Year' : ['2007'], 
                          'Keyword' : ['CD', 'Trance'],
                          'Rating' : ['4 stars']
                        }
                    ],
                    [
                        'B00005JPLW',
                        {
                          'Title' : ['300'], 
                          'Author' : ['Zack Snyder'], 
                          'Year' : ['2007'], 
                          'Keyword' : ['DVD', 'Action', 'Frank Miller'],
                          'Rating' : ['***','3 stars','Not bad']
                        }
                    ],
                    [
                        'B000SF3NGK',
                        {
                          'Title' : ['Heaven\'s Gonna Burn Your Eyes'], 
                          'Author' : ['Thievery Corporation'], 
                          'Year' : ['2002'], 
                          'Rating' : ['*****']
                        }
                    ]
                    
                ]

        for insert in inserts:
            self._testInsert(insert[0], insert[1])

    def _testInsert(self, itemName, attrs):
        s = SimpleDBDev()
        
        input = {
                 'ItemName' : itemName,
                 'DomainName' : self.domain
                 }
        
        self._convertAttrs(attrs, input)
        
        s.PutAttributes(input)
    
if __name__ == "__main__": 
    if len(sys.argv) > 1 and str(sys.argv[1]) == 'test' :
        SimpleDBTest().run()
    else :
        web.run(urls, globals(), web.reloader)
