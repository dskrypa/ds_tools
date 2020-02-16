"""
Example usage::

    >>> iso = MediaWikiClient.page_for_article('https://en.wikipedia.org/wiki/ISO_8601')
    2020-02-16 10:51:52 EST DEBUG requests_client.client 195 GET -> https://en.wikipedia.org/w/api.php?titles=ISO_8601&rvprop=content&prop=revisions%7Ccategories&action=query&redirects=1&cllimit=500&rvslots=main&format=json&formatversion=2&utf8=1

    >>> iso.sections.pprint()
    <Section[0: ]>
        <Section[2: History]>
            <Section[3: List]>
        <Section[2: General principles]>
        <Section[2: Dates]>
            <Section[3: Years]>
            <Section[3: Calendar dates]>
            <Section[3: Week dates]>
            <Section[3: Ordinal dates]>
        <Section[2: Times]>
            <Section[3: Time zone designators]>
                <Section[4: Coordinated Universal Time (UTC)]>
                <Section[4: Time offsets from UTC]>
        <Section[2: Combined date and time representations]>
        <Section[2: Durations]>
        <Section[2: Time intervals]>
            <Section[3: Repeating intervals]>
        <Section[2: Truncated representations]>
        <Section[2: Usage]>
            <Section[3: Commerce]>
            <Section[3: RFCs]>
            <Section[3: Adoption as national standards]>
        <Section[2: See also]>
        <Section[2: Notes and references]>
        <Section[2: External links]>

    >>> for row in iso.sections['History']['List'].content:
    ...     row
    ...
    <MappingNode({'Name': <String('ISO 8601:1988')>, 'Description': <String('Data elements and interchange formats -- Information interchange -- Representation of dates and times')>})>
    <MappingNode({'Name': <String('ISO 8601:1988/COR 1:1991')>, 'Description': <String('')>})>
    <MappingNode({'Name': <String('ISO 8601:2000')>, 'Description': <String('Data elements and interchange formats — Information interchange — Representation of dates and times')>})>
    <MappingNode({'Name': <String('ISO 8601:2004')>, 'Description': <String('Data elements and interchange formats -- Information interchange -- Representation of dates and times')>})>
    <MappingNode({'Name': <String('ISO 8601-1:2019')>, 'Description': <String('Date and time -- Representations for information interchange -- Part 1: Basic rules')>})>
    <MappingNode({'Name': <String('ISO 8601-2:2019')>, 'Description': <String('Date and time -- Representations for information interchange -- Part 2: Extensions')>})>

    >>> iso.intro
    <CompoundNode([<String("'''ISO 8601''' ''Data elements and interchange formats – Information interchange – Representation of dates and times'' is an")>, <Link:'[[international standard]]'@wikipedia>, <String('covering the exchange of')>, <Link:'[[Calendar date|date]]'@wikipedia>, <String('- and')>, <Link:'[[time]]'@wikipedia>, <String('-related data. It was issued by the')>, <Link:'[[International Organization for Standardization]]'@wikipedia>, <String('(ISO) and was first published in 1988. The purpose of this standard is to provide an unambiguous and well-defined method of representing dates and times, so as to avoid misinterpretation of numeric representations of dates and times, particularly when data is transferred between')>, <Link:'[[Date and time notation by country|countries with different conventions]]'@wikipedia>, <String('for writing numeric dates and times.\n\nIn general, ISO 8601 applies to representations and formats of dates in the')>, <Link:'[[Gregorian calendar|Gregorian]]'@wikipedia>, <String('(and potentially')>, <Link:'[[proleptic Gregorian calendar|proleptic Gregorian]]'@wikipedia>, <String(') calendar, of times based on the')>, <Link:'[[24-hour clock|24-hour timekeeping system]]'@wikipedia>, <String('(with optional')>, <Link:'[[UTC offset]]'@wikipedia>, <String('), of')>, <Link:'[[Time interval#Time-like concepts: terminology|time intervals]]'@wikipedia>, <String(', and combinations thereof.')>, <Tag[ref:{'name': 'scope'}][ISO 8601:2004[E] section 1 Scope]>, <String('The standard does not assign any specific meaning to elements of the date/time to be represented; the meaning will depend on the context of its use.  In addition, dates and times to be represented cannot include words with no specified numerical meaning in the standard (e.g., names of')>, <Link:'[[Chinese calendar correspondence table|years in the Chinese calendar]]'@wikipedia>, <String(') or that do not use')>, <Link:'[[Character (computing)|characters]]'@wikipedia>, <String('(e.g., images, sounds).')>, <Tag[ref:{'name': 'scope'}][]>, <String('In representations for interchange, dates and times are arranged so the largest temporal term (the year) is placed to the left and each successively smaller term is placed to the right of the previous term. Representations must be written in a combination of')>, <Link:'[[Arabic numerals]]'@wikipedia>, <String('and certain characters (such as "-", ":", "T", "W", and "Z") that are given specific meanings within the standard; the implication is that some commonplace ways of writing parts of dates, such as "January" or "Thursday", are not allowed in interchange representations.')>])>

    >>> iso.infobox
    <Template('Infobox': <MappingNode({'title': <String('Date and time expressed according to ISO 8601 <small>[{{purge|refresh}}]</small>')>, 'label1': <String('Date')>, 'data1': <Template('ISO date': None)>, 'label2': <CompoundNode([<String('Date and time in')>, <Link:'[[UTC]]'@wikipedia>])>, 'data2': <CompoundNode([<Template('nobreak': <String('{{#time:c}}')>)>, <Tag[br][]>, <String('{{#time: Y-m-d"T"H:i:s"Z"}}')>, <Tag[br][]>, <String('{{#time: Ymd"T"His"Z"}}')>])>, 'label3': <String('Week')>, 'data3': <String('{{#time: o-"W"W}}')>, 'label4': <String('Date with week number')>, 'data4': <String('{{#time: o-"W"W-N}}')>, 'label5': <String('Date without year')>, 'data5': <CompoundNode([<Template('date': [<String('{{#time: --m-d}}')>, <String('ISO')>])>, <Tag[ref][<CompoundNode([<String('last in ISO8601:2000, in use by')>, <Template('cite web': <MappingNode({'url': <String('https://tools.ietf.org/html/rfc6350#section-4.3.1')>, 'title': <String('RFC 6350 - vCard Format Specification')>, 'accessdate': <String('2016-06-29')>, 'date': <String('August 2011')>, 'publisher': <Link:'[[Internet Engineering Task Force|IETF]]'@wikipedia>, 'quote': <String('Truncated representation, as specified in [ISO.8601.2000], Sections 5.2.1.3 d), e), and f), is permitted.')>})>)>])>]>])>, 'label6': <Link:'[[Ordinal date]]'@wikipedia>, 'data6': <CompoundNode([<Template('CURRENTYEAR': None)>, <String('-{{padleft:{{#expr:{{#time: z}}+1}}|3}}')>])>})>)>

:author: Doug Skrypa
"""
