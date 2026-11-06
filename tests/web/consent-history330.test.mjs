import test from 'node:test';
import assert from 'node:assert/strict';
import {appendDetailSections} from '../../src/chronos_web/detail.mjs';
class Element {
 constructor(tag,ownerDocument){this.tag=tag;this.ownerDocument=ownerDocument;this.children=[];this.attrs={};this._text='';}
 set textContent(v){this._text=String(v);this.children=[];} get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
 appendChild(c){this.children.push(c);c.parentNode=this;return c;} setAttribute(k,v){this.attrs[k]=v;}
}
const flat=x=>[x,...x.children.flatMap(flat)];
function draw(sections){const d={createElement(tag){return new Element(tag,d);}},root=new Element('main',d);appendDetailSections(d,root,sections);return root;}
const section=(title,rows=[],table=null)=>({title,note:'note:'+title,rows,table});
const history=[section('Recorded proposal',[{label:'Action',value:'FAILOVER_B'}]),section('Source catalog',[{label:'Source',value:'fact:policy'}]),section('Recorded alternatives',[],{headers:['Option','Action','Cost','Available','Queue','Travel'],rows:[['A','RETRY_A','3','time','0 s','780 s'],['B','FAILOVER_B','6','time','0 s','540 s']]})];
const critical=Object.freeze(['Destination','Cost units','Order','Operation','Data revision','Policy revision','Exact payload JSON','Delivery deadline (UTC)','Offer valid until (UTC)','Inventory until (UTC)'].map(label=>Object.freeze({label,value:'exact:'+label})));
test('330 consent keeps all fresh fields and Before confirming outside closed history',()=>{
 const sections=[...history,section('Before confirming',[{label:'Result',value:'Acceptance is not delivery'}]),section('Fresh server preview',critical)];
 const before=JSON.stringify(sections),root=draw(sections),fold=root.children.find(x=>x.tag==='details');
 assert(fold);assert.equal(fold.children[0].tag,'summary');assert.equal(fold.children[0].textContent,'Recorded decision and supporting evidence');assert.equal(fold.attrs.open,undefined);assert.equal(fold.open,undefined);
 assert.equal(root.children[0].children[0].textContent,'Fresh server preview');assert.equal(root.children[1].children[0].textContent,'Before confirming');
 for(const r of critical){assert(root.children[0].textContent.includes(r.label));assert(root.children[0].textContent.includes(r.value));assert(!fold.textContent.includes(r.value));}
 assert(!fold.textContent.includes('Acceptance is not delivery'));assert.equal(JSON.stringify(sections),before);
 for(const text of ['FAILOVER_B','fact:policy','780 s','540 s','Historical offer'])assert(fold.textContent.includes(text));
 assert(!flat(fold).some(x=>['button','input','form'].includes(x.tag)));
});
test('330 ordinary decision retains expanded alternative cards and no combined fold',()=>{
 const root=draw(history);assert(!flat(root).some(x=>x.tag==='summary'&&x.textContent==='Recorded decision and supporting evidence'));
 const options=root.children.find(x=>x.children[0]?.textContent==='Recorded alternatives');assert.equal(options.tag,'section');assert(flat(options).some(x=>x.className==='chronos-options'));
});
test('330 no historical section produces no empty disclosure',()=>{
 const root=draw([section('Fresh server preview',critical),section('Before confirming')]);assert.equal(root.children.length,2);assert(!root.children.some(x=>x.tag==='details'));
});
