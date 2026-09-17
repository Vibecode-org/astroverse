import React from 'react';

const SearchBar = ({ query, setQuery }) => {
  return (
    <div className="searchBox">
      <span>⌕</span>
      <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Найти звезду, планету, туманность…" />
    </div>
  );
};

export default SearchBar;