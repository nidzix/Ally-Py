'''
Created on Mar 27, 2013

@package: assemblage service
@copyright: 2011 Sourcefabric o.p.s.
@license: http://www.gnu.org/licenses/gpl-3.0.txt
@author: Gabriel Nistor

Provides the assembler processor.
'''

from ally.assemblage.http.spec.assemblage import IRepository, Matcher, \
    Assemblage
from ally.container import wire
from ally.container.ioc import injected
from ally.design.processor.assembly import Assembly
from ally.design.processor.attribute import requires, defines, optional
from ally.design.processor.branch import Using
from ally.design.processor.context import Context, pushIn
from ally.design.processor.execution import Processing, Chain
from ally.design.processor.handler import HandlerBranchingProceed
from ally.http.spec.codes import isSuccess
from ally.http.spec.server import IDecoderHeader, ResponseHTTP, RequestHTTP, \
    HTTP_GET
from ally.support.util_io import IInputStream
from codecs import getreader, getwriter
from collections import Iterable
from io import BytesIO
from urllib.parse import urlsplit, parse_qsl
import logging

# --------------------------------------------------------------------

NAME_ERROR_STATUS = 'ERROR'
# The error status injector name
NAME_ERROR_TEXT = 'ERROR_TEXT'
# The error text injector name

UNKNOWN_ENCODING = 417, 'Unknown encoding'  # HTTP code 417 Expectation Failed
RESPONSE_TO_LARGE = 417, 'Response to large'  # HTTP code 417 Expectation Failed

log = logging.getLogger(__name__)

# --------------------------------------------------------------------

class Request(Context):
    '''
    The request context.
    '''
    # ---------------------------------------------------------------- Optional
    parameters = optional(list)
    # ---------------------------------------------------------------- Required
    scheme = requires(str)
    method = requires(str)
    headers = requires(dict)
    uri = requires(str)
    repository = requires(IRepository)
    decoderHeader = requires(IDecoderHeader)

class ResponseContent(Context):
    '''
    The response content context.
    '''
    # ---------------------------------------------------------------- Defined
    length = defines(int)
    
class ResponseContentData(Context):
    '''
    The response content context containing data for assemblage.
    '''
    # ---------------------------------------------------------------- Required
    type = requires(str)
    charSet = requires(str)
    source = requires(IInputStream, Iterable)
    length = requires(int)

# --------------------------------------------------------------------

@injected
class AssemblerHandler(HandlerBranchingProceed):
    '''
    Implementation for a handler that provides the assembling.
    '''
    
    maximum_length = 1024 * 100; wire.config('maximum_length', doc='''
    The maximum response length in bytes allowed for injecting''')
    nameAssemblage = 'X-Filter'
    # The header name for the assemblage request.
    assembly = Assembly
    # The assembly to be used in processing the request.
    
    def __init__(self):
        assert isinstance(self.maximum_length, int), 'Invalid maximum response length %s' % self.maximum_length
        assert isinstance(self.nameAssemblage, str), 'Invalid assemblage name %s' % self.maximum_response_length
        assert isinstance(self.assembly, Assembly), 'Invalid assembly %s' % self.assembly
        super().__init__(Using(self.assembly, 'request', 'requestCnt', response=ResponseHTTP, responseCnt=ResponseContentData))

    def process(self, processing, request:Request, requestCnt:Context, response:Context,
                responseCnt:ResponseContent, **keyargs):
        '''
        @see: HandlerBranchingProceed.process
        
        Assemble response content.
        '''
        assert isinstance(processing, Processing), 'Invalid processing %s' % processing
        assert isinstance(request, Request), 'Invalid request %s' % request
        assert isinstance(responseCnt, ResponseContent), 'Invalid response content %s' % responseCnt
        assert isinstance(request.decoderHeader, IDecoderHeader), 'Invalid decoder header %s' % request.decoderHeader
        
        names = request.decoderHeader.decode(self.nameAssemblage)
        if names:
            # We capture the URI and data here since the data on request might be change by internal processing.
            uri, data = request.uri, dict(scheme=request.scheme, headers=dict(request.headers))
            # We capture the parameters used on sub responses.
            namesWithParams = {}
            #TODO: implement parameters distribution, see a way to capture parameters without using the names, maybe use the
            # lower case convention.
            names = set(name for name, _attr in names)
            for name in sorted(names, key=lambda name: len(name), reverse=True):
                k, namePrefix = 0, '%s.' % name
                while k < len(request.parameters):
                    nameParam, valueParam = request.parameters[k]
                    assert isinstance(nameParam, str), 'Invalid name %s' % nameParam
                    if nameParam.startswith(namePrefix):
                        params = namesWithParams.get(name)
                        if params is None: params = namesWithParams[name] = []
                        params.append((nameParam[len(namePrefix):], valueParam))
                        # TODO: remove
                        print(request.parameters[k])
                        del request.parameters[k]
                    else: k += 1
        
        isOk, responseData, responseCntData = self.fetchResponse(processing, request, requestCnt)
        assert isinstance(responseCntData, ResponseContentData), 'Invalid response content %s' % responseCntData
        
        pushIn(response, responseData)
        pushIn(responseCnt, responseCntData)
        assert isinstance(responseCnt, ResponseContentData), 'Invalid response content %s' % responseCnt
        
        if not isOk or not names: return
        # The main request has failed or has no content or no assemblages required, nothing to do just move along.
        
        assert isinstance(request.repository, IRepository), 'Invalid repository %s' % request.repository
        assemblage = request.repository.assemblage(responseCnt.type)
        if not assemblage: return
        # No assemblage to process, nothing to do.
        data.update(processing=processing, assemblage=assemblage, repository=request.repository)
        isOk, matchers = self.processURI(names=names, method=request.method, uri=uri, isTrimmed=False, **data)
        
        if not isOk: return
        # No valid matchers to process.
        
        content, error = self.fetchContent(responseCnt)
        if not content:
            log.warn('Cannot fetch content for \'%s\' because:%s', uri, error)
            return
        
        assembled = self.assemble(assemblage, matchers, content, data)
        
        source = BytesIO()
        encoder = getwriter(responseCnt.charSet)(source)
        for content in assembled: encoder.write(content)
        responseCnt.length = source.tell()
        source.seek(0)
        responseCnt.source = source
        
    # ----------------------------------------------------------------
        
    def fetchResponse(self, processing, request, requestCnt=None):
        '''
        Fetch the response for the request.
        
        @param processing: Processing
            The processing used for delivering the request.
        @param request: RequestHTTP
            The request object to deliver.
        @return: tuple(boolean, ResponseHTTP, ResponseContentHTTP)
            A tuple of three containing a flag indicating the success status and then the response and response content.
        '''
        assert isinstance(processing, Processing), 'Invalid processing %s' % processing
        
        if requestCnt is None: requestCnt = processing.ctx.requestCnt()
        chain = Chain(processing)
        chain.process(request=request, requestCnt=requestCnt,
                      response=processing.ctx.response(), responseCnt=processing.ctx.responseCnt()).doAll()
    
        response, responseCnt = chain.arg.response, chain.arg.responseCnt
        assert isinstance(response, ResponseHTTP), 'Invalid response %s' % response
        assert isinstance(responseCnt, ResponseContentData), 'Invalid response content %s' % responseCnt
        
        isOk = ResponseContentData.source in responseCnt and responseCnt.source is not None and isSuccess(response.status)
        return isOk, response, responseCnt
    
    def fetchContent(self, responseCnt):
        '''
        Fetches the text content into a string, None if the content type is no usable.
        
        @param responseCnt: ResponseContentData
            The response content to fetch the content from.
        @return: tuple(string|None, tuple(integer, string|None))
            A tuple of two, on the first position the content string or None if a problem occurred, and on the second position
            the error explanation if there was a problem, the error is provided as a tuple having on the first position the
            HTTP status code and on the second text explanation.
        '''
        assert isinstance(responseCnt, ResponseContentData), 'Invalid response content %s' % responseCnt
        
        try: decoder = getreader(responseCnt.charSet)
        except LookupError: return None, UNKNOWN_ENCODING
        
        if responseCnt.length > self.maximum_length: return None, RESPONSE_TO_LARGE
        
        if isinstance(responseCnt.source, IInputStream):
            source = responseCnt.source
        else:
            source = BytesIO()
            for bytes in responseCnt.source: source.write(bytes)
            source.seek(0)
        
        return decoder(source).read(), None
    
    # ----------------------------------------------------------------
        
    def assemble(self, assemblage, matchers, content, data):
        '''
        Process the assemble.
        '''
        assert isinstance(assemblage, Assemblage), 'Invalid assemblage %s' % assemblage
        assert isinstance(matchers, list), 'Invalid matchers %s' % matchers
        assert isinstance(content, str), 'Invalid content %s' % content
        assert isinstance(data, dict), 'Invalid data %s' % data
        
        while matchers:
            matcher, include, names = matchers.pop()
            assert isinstance(matcher, Matcher), 'Invalid matcher %s' % matcher
            
            if not include: break  # We need to exclude the matchers block so proceed with the matcher.
            if matcher.reference:
                if names: break  # We need to process the reference with names so proceed with the matcher
                elif not matcher.present: break  # No present info so we need to get some.
        else:
            # No matcher needs processing
            return (content,)
        
        assembled, current = [], 0
        for match in matcher.pattern.finditer(content):
            mcontent = content[current:match.start()]
            if matchers: assembled.extend(self.assemble(assemblage, list(matchers), mcontent, data))
            else: assembled.append(mcontent)
            current = match.end()
            
            if not include: continue  # We exclude the block
            
            block = match.group()
            rmatch = matcher.reference.search(block)
            if rmatch:
                for reference in rmatch.groups():
                    if reference: break
                else:
                    assert log.debug('No URI reference located in:\n%s', block) or True
                    assembled.append(block)
                    continue
                
                rurl = urlsplit(reference)
                ruri = rurl.path.lstrip('/')
                rparameters = parse_qsl(rurl.query, True, False)
                
                isOk, smatchers = self.processURI(names=names, uri=ruri, **data)
                if not isOk:
                    # No matchers to process on the reference content and we have present to show
                    assembled.append(block)
                    continue
                    
                rcontent, error = self.contentURI(ruri, rparameters, **data)
                # TODO: remove
                # rcontent, error = None, (201, 'MUEEEEEEE')
                if not rcontent:
                    status, text = error
                    assert log.debug('Cannot fetch content for \'%s\' because: %s %s', ruri, status, text) or True
                    error = assemblage.errors.get(NAME_ERROR_STATUS)
                    if error:
                        ereplacer, epattern = error
                        epattern = epattern.replace('*', str(status))
                        block = ereplacer.sub(epattern, block)
                    error = assemblage.errors.get(NAME_ERROR_TEXT)
                    if error:
                        ereplacer, epattern = error
                        epattern = epattern.replace('*', str(text))
                        block = ereplacer.sub(epattern, block)
                    
                    assembled.append(block)
                    continue
                
                if smatchers:
                    sassembled = self.assemble(assemblage, smatchers, rcontent, data)
                    rcontent = ''.join(sassembled)
                
                groups = match.groups()
                for replacer, pattern in assemblage.adjusters:
                    for k, group in enumerate(groups):
                        pattern = pattern.replace('{%s}' % (k + 1), group)
                    rcontent = replacer.sub(pattern, rcontent)
                
                assembled.append(rcontent)
        
        mcontent = content[current:]
        if matchers: assembled.extend(self.assemble(assemblage, matchers, mcontent, data))
        else: assembled.append(mcontent)
        
        return assembled
        
    def contentURI(self, uri, parameters, scheme, headers, processing, **data):
        '''
        Fetches the content for the provided URI.
        
        @param uri: string
            The URI to fetch the content for.
        @param parameters: list[tuple(string, string)]|None
            The parameters of the URI.
        @param scheme: string
            The scheme for the request.
        @param headers: dictionary{string: string}
            The headers to use on the request.
        @param processing: Processing
            The processing to use for the request.
        @return: tuple(string|None, tuple(integer, string|None))
            A tuple of two, on the first position the content string or None if a problem occurred, and on the second position
            the error explanation if there was a problem, the error is provided as a tuple having on the first position the
            HTTP status code and on the second text explanation.
        '''
        assert isinstance(uri, str), 'Invalid uri %s' % uri
        assert isinstance(parameters, list), 'Invalid parameters %s' % parameters
        assert isinstance(processing, Processing), 'Invalid processing %s' % processing
        assert isinstance(scheme, str), 'Invalid scheme %s' % scheme
        assert isinstance(headers, dict), 'Invalid headers %s' % headers
        
        request = processing.ctx.request()
        assert isinstance(request, RequestHTTP), 'Invalid request %s' % request
        
        request.scheme = scheme
        request.method = HTTP_GET
        request.headers = dict(headers)
        request.uri = uri
        request.parameters = parameters
        
        isOk, response, responseCnt = self.fetchResponse(processing, request)
        if not isOk:
            assert isinstance(response, ResponseHTTP), 'Invalid response %s' % response
            if ResponseHTTP.text in response and response.text: text = response.text
            elif ResponseHTTP.code in response and response.code: text = response.code
            else: text = None
            return None, (response.status, text)
        return self.fetchContent(responseCnt)

    def processURI(self, names=None, isTrimmed=True, **data):
        '''
        Provides the matchers that are associated with the provided names.

        @param names: Iterable(string)|None
            The set of names to associate with the matchers.
        @param isTrimmed: boolean
            Flag indicating that the unassociated matchers should be trimmed from the response.
        @return: tuple(boolean, list[tuple(Matcher, boolean, list[string]|None)]|None)
            A tuple having on the first position a flag indicating if the assembly should continue (True) or stop here (False).
            On the second position it has a list of tuples containing on the first position the matcher, next the flag 
            indicating that the matcher content should be excluded or included and last the names to be fetched inside the 
            matcher assembly if there are any, basically (matcher, include(True) or exclude(False), sub names)
            None if no matchers could be associated.
        '''
        assert isinstance(isTrimmed, bool), 'Invalid is trimmed flag %s' % isTrimmed
        
        matchers = self.matchersURI(**data)
        if not matchers: return False, None
        assert isinstance(matchers, Iterable), 'Invalid matchers %s' % matchers
        matchers = list(matchers)
        
        for matcher in matchers:
            assert isinstance(matcher, Matcher), 'Invalid matcher %s' % matcher
            if matcher.name is None:
                if names: return True, [(matcher, True, list(names))]
                return True, None
        
        if names is None:
            if len(matchers) == 1: return True, None  # If it just one matcher then we do not need to exclude others
            matcher = matchers[0]
            assert isinstance(matcher, Matcher), 'Invalid matcher %s' % matcher
            names, isTrimmed = (matcher.name,), True  # We keep only this name, the others will be excluded
        assert isinstance(names, Iterable), 'Invalid names %s' % names
        
        names, matchers, matchersByName, subNamesForName, missing = list(names), iter(matchers), {}, {}, []
        for matcher in matchers:
            assert isinstance(matcher, Matcher), 'Invalid matcher %s' % matcher
            isFound, k = False, 0
            while k < len(names):
                name = names[k]
                assert isinstance(name, str), 'Invalid name %s' % name
                if name == matcher.name:
                    isFound = True
                    matchersByName[name] = matcher
                    del names[k]
                elif name.startswith(matcher.namePrefix):
                    isFound = True
                    name, sname = name[:len(matcher.namePrefix) - 1], name[len(matcher.namePrefix):]
                    matchersByName[name] = matcher
                    subNames = subNamesForName.get(name)
                    if subNames is None: subNames = subNamesForName[name] = []
                    subNames.append(sname)
                    del names[k]
                else: k += 1
            if not isFound: missing.append(matcher)
            if not names:
                missing.extend(matchers)
                break
        
        if isTrimmed and '*' in names: isTrimmed = False
        if isTrimmed and not matchersByName: return False, None
        
        associated = []
        for name, matcher in matchersByName.items():
            subNames = subNamesForName.get(name)
            if isTrimmed and subNames:
                if matcher.present:
                    assert isinstance(matcher.present, set)
                    if matcher.present.issuperset(subNames): continue
                    # If the sub names are already present then no need to add the matcher.
                
            associated.append((matcher, True, subNames))
            
        if isTrimmed:
            for matcher in missing: associated.append((matcher, False, None))
        
        return True, associated
    
    def matchersURI(self, assemblage, uri, repository, headers, method=HTTP_GET, **data):
        '''
        Provides the matchers obtained for URI directly associated with the provided names.
        
        @param assemblage: Assemblage
            The assemblage to search the matchers in.
        @param uri: string
            The URI to get the matchers for.
        @param names: set(string)|list[string]
            The set of names to associate with the URI matchers.
        @param repository: IRepository
            The repository used in getting the URI matchers.
        @param headers: dictionary{string: string}
            The headers to to be used on the matchers.
        @param method: string
            The method operated on the URI.
        @return: Iterable(Matcher)|None
            The found matchers, None if there are no matchers 
             available.
        '''
        assert isinstance(repository, IRepository), 'Invalid repository %s' % repository
        return repository.matchers(assemblage, method, uri, headers)