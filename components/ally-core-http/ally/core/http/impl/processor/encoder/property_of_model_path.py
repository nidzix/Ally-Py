'''
Created on Mar 8, 2013

@package: ally core http
@copyright: 2011 Sourcefabric o.p.s.
@license: http://www.gnu.org/licenses/gpl-3.0.txt
@author: Gabriel Nistor

Provides the paths for properties of model.
'''

from ally.api.operator.type import TypeModel, TypeModelProperty
from ally.container.ioc import injected
from ally.core.http.spec.transform.flags import ATTRIBUTE_REFERENCE
from ally.core.spec.resources import Path, Normalizer
from ally.core.spec.transform.encoder import IAttributes, AttributesJoiner
from ally.core.spec.transform.representation import Attribute
from ally.design.cache import CacheWeak
from ally.design.processor.attribute import requires, defines, optional
from ally.design.processor.context import Context
from ally.design.processor.handler import HandlerProcessorProceed
from ally.http.spec.server import IEncoderPath

# --------------------------------------------------------------------
    
class Create(Context):
    '''
    The create encoder context.
    '''
    # ---------------------------------------------------------------- Defined
    attributes = defines(IAttributes, doc='''
    @rtype: IAttributes
    The attributes with the paths.
    ''')
    # ---------------------------------------------------------------- Required
    objType = requires(object)
    
class Support(Context):
    '''
    The encoder support context.
    '''
    # ---------------------------------------------------------------- Optional
    encoderPath = optional(IEncoderPath)
    # ---------------------------------------------------------------- Required
    normalizer = requires(Normalizer)
    pathsProperties = requires(dict)
    
# --------------------------------------------------------------------

@injected
class PropertyOfModelPathAttributeEncode(HandlerProcessorProceed):
    '''
    Implementation for a handler that provides the path encoding in attributes.
    '''
    
    nameRef = 'href'
    # The reference attribute name.
    
    def __init__(self):
        assert isinstance(self.nameRef, str), 'Invalid reference name %s' % self.nameRef
        super().__init__(support=Support)
        
        self._cache = CacheWeak()
        
    def process(self, create:Create, **keyargs):
        '''
        @see: HandlerProcessorProceed.process
        
        Create the path attributes.
        '''
        assert isinstance(create, Create), 'Invalid create %s' % create
        
        if not isinstance(create.objType, TypeModelProperty) or not isinstance(create.objType.type, TypeModel): return
        # The type is not for a model property, nothing to do, just move along
            
        modelType = create.objType.type
        assert isinstance(modelType, TypeModel)
        assert modelType.hasId(), 'Model type %s, has no id' % modelType
        
        if create.attributes: attributes = create.attributes
        else: attributes = None
        
        cache = self._cache.key(modelType, attributes)
        if not cache.has: cache.value = AttributesPath(self.nameRef, modelType.propertyTypeId(), attributes)
        create.attributes = cache.value

# --------------------------------------------------------------------

class AttributesPath(AttributesJoiner):
    '''
    Implementation for a @see: IAttributes for paths.
    '''
    
    def __init__(self, nameRef, propertyType, attributes=None):
        '''
        Construct the paths attributes.
        '''
        assert isinstance(nameRef, str), 'Invalid reference name %s' % nameRef
        assert isinstance(propertyType, TypeModelProperty), 'Invalid property type %s' % propertyType
        super().__init__(attributes)
        
        self.nameRef = nameRef
        self.propertyType = propertyType
        
    def provideIntern(self, obj, support):
        '''
        @see: AttributesJoiner.provideIntern
        '''
        assert isinstance(support, Support), 'Invalid support %s' % support
        if not support.pathsProperties: return  # No paths for models.
        
        assert isinstance(support.normalizer, Normalizer), 'Invalid normalizer %s' % support.normalizer
        assert isinstance(support.pathsProperties, dict), 'Invalid properties paths %s' % support.pathsProperties
        assert Support.encoderPath in support, 'No path encoder available in %s' % support
        assert isinstance(support.encoderPath, IEncoderPath), 'Invalid path encoder %s' % support.encoderPath
        
        path = support.pathsProperties.get(self.propertyType)
        if not path: return  # No path to construct attributes for.
        assert isinstance(path, Path), 'Invalid path %s' % path
        path.update(obj, self.propertyType)
        return {support.normalizer.normalize(self.nameRef): support.encoderPath.encode(path)}
    
    def representIntern(self, support):
        '''
        @see: AttributesJoiner.representIntern
        '''
        assert isinstance(support, Support), 'Invalid support %s' % support
        if not support.pathsProperties: return  # No paths for models.
        
        assert isinstance(support.normalizer, Normalizer), 'Invalid normalizer %s' % support.normalizer
        assert isinstance(support.pathsProperties, dict), 'Invalid properties paths %s' % support.pathsProperties
        
        path = support.pathsProperties.get(self.propertyType)
        if not path: return  # No path to construct attributes for.
        return {support.normalizer.normalize(self.nameRef): Attribute(ATTRIBUTE_REFERENCE)}