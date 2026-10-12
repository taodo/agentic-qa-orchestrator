// Test-only RFC-style CSV reader to check round trips, including quoted CR/LF.
export function readCsv(text:string):string[][] {
  const rows:string[][]=[];let row:string[]=[],cell='',quoted=false;
  for(let i=0;i<text.length;i++){
    const char=text[i];
    if(char==='"'){if(quoted && text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
    else if(!quoted && char===','){row.push(cell);cell='';}
    else if(!quoted && (char==='\r' || char==='\n')){if(char==='\r' && text[i+1]==='\n')i++;row.push(cell);rows.push(row);row=[];cell='';}
    else cell+=char;
  }
  if(cell || row.length){row.push(cell);rows.push(row);}return rows;
}
