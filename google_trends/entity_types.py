
# Currently hard coded to retrive anything with 'company' in entity type if 'company is included in PRIMARY_TYPES
# This is in line 52 of disambiguate.py
# Remove 'company' from primary_types and define your own entity types.

PRIMARY_TYPES = {
    'automaker company',
    'airline',
    'airline company',
    'all other miscellaneous manufacturing business',
    'bank',
    'broadcasting company',
    'business',
    'business operation',
    'business process outsourcing company',
    'commercial banking company',
    'commercial bank business',
    'commercial company',
    'commercial organization',
    'computer-aided engineering company',
    'company',
    'conglomerate company',
    'construction company',
    'consumer electronics company',
    'corporation',
    'crude petroleum and natural gas extraction business',
    'defense contractor business',
    'energy company',
    'electronics company',
    'financial services company',
    'finance company',
    'game developer',
    'health care company',
    'healthcare company',
    'investment',
    'investment company',
    'investment banking company',
    'internet company',
    'it security company',
    'logistics company',
    'management services consulting company',
    'management consulting services company',
    'mining company',
    'motion picture company',
    'mobile marketing company',
    'mobile network operator company',
    'motherboard company',
    'music industry company',
    'natural gas transmission company',
    'network security company',
    'online shopping company',
    'organization',
    'petroleum industry business',
    'petroleum refineries company',
    'private equity company',
    'pharmaceutical company',
    'pharmaceutical preparations business',
    'risk management company',
    'retail company',
    'real estate company',
    'restaurant',
    'service',
    'semiconductor manufacturing company',
    'software company',
    'software developer',
    'software engineering company',
    'specialty retailer company',
    'solar power company',
    'solar power business',
    'software development company',
    'software as a service company',
    'social network service website',
    'shoe manufacturing company',
    'telecommunications company',
    'video game developer',
    'website',
}

BACKUP_TYPES = {
    'organization leader',
    'organization founder',
    'brand',
    'topic',
    'software',
    'fashion designer',
    'trucking, except local business'
}
